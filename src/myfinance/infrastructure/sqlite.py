"""SQLite persistence adapters.

Every operation opens its own short-lived connection inside a worker thread so
the event loop never blocks. There is deliberately no global connection or
module-level singleton.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from myfinance.domain.banking import (
    BankAccount,
    BankIdentity,
    BankTransaction,
    PluggyItem,
)
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.models import ChatMessage
from myfinance.domain.money import Money

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_entry_date ON entries(entry_date);

CREATE TABLE IF NOT EXISTS processed_updates (
    update_id INTEGER PRIMARY KEY,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pluggy_items (
    item_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    error TEXT,
    connector_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pluggy_accounts (
    account_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    balance_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pluggy_transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    category TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pluggy_identity (
    item_id TEXT PRIMARY KEY,
    full_name TEXT,
    document TEXT,
    document_type TEXT,
    birth_date TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_chat ON conversation_messages(chat_id, id);
"""


class SqliteDatabase:
    """Creates the schema and hands out configured connections."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def connect(self) -> sqlite3.Connection:
        """Open a new connection configured for concurrent WAL access."""
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _create_schema(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.executescript(_SCHEMA)
                self._migrate_pluggy_items(connection)

    @staticmethod
    def _migrate_pluggy_items(connection: sqlite3.Connection) -> None:
        """Add ``connector_name`` to databases created before it existed."""
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(pluggy_items)"
            ).fetchall()
        }
        if "connector_name" not in columns:
            connection.execute(
                "ALTER TABLE pluggy_items ADD COLUMN connector_name TEXT"
            )


class SqliteEntryRepository:
    """Persists :class:`Entry` rows in SQLite."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def add(self, entry: Entry) -> None:
        await asyncio.to_thread(self._add, entry)

    async def list_by_day(self, day: date) -> Sequence[Entry]:
        return await asyncio.to_thread(self._list_by_day, day)

    async def list_between(self, start: date, end: date) -> Sequence[Entry]:
        return await asyncio.to_thread(self._list_between, start, end)

    def _add(self, entry: Entry) -> None:
        with closing(self._database.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO entries (
                        id, kind, entry_date, amount_cents,
                        description, category, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(entry.id),
                        entry.kind.value,
                        entry.day.isoformat(),
                        entry.amount.cents,
                        entry.description,
                        entry.category.value,
                        entry.created_at.isoformat(),
                    ),
                )

    def _list_by_day(self, day: date) -> Sequence[Entry]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, kind, entry_date, amount_cents,
                       description, category, created_at
                FROM entries
                WHERE entry_date = ?
                ORDER BY created_at, rowid
                """,
                (day.isoformat(),),
            ).fetchall()
        return tuple(self._row_to_entry(row) for row in rows)

    def _list_between(self, start: date, end: date) -> Sequence[Entry]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, kind, entry_date, amount_cents,
                       description, category, created_at
                FROM entries
                WHERE entry_date >= ?
                  AND entry_date <= ?
                ORDER BY created_at, rowid
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return tuple(self._row_to_entry(row) for row in rows)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> Entry:
        return Entry(
            id=UUID(row["id"]),
            kind=EntryKind(row["kind"]),
            day=date.fromisoformat(row["entry_date"]),
            amount=Money(row["amount_cents"]),
            description=row["description"],
            category=Category(row["category"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class SqliteProcessedUpdateRepository:
    """Claims chat updates exactly once, relying on the primary key."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def claim(self, update_id: int) -> bool:
        return await asyncio.to_thread(self._claim, update_id)

    def _claim(self, update_id: int) -> bool:
        with closing(self._database.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO processed_updates (
                        update_id, processed_at
                    ) VALUES (?, ?)
                    """,
                    (update_id, datetime.now(UTC).isoformat()),
                )
                return cursor.rowcount == 1


class SqliteConversationMemory:
    """Keeps the last exchanges of each chat in SQLite."""

    _MAX_ROWS = 10

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def append(
        self, chat_id: str, role: Literal["user", "assistant"], content: str
    ) -> None:
        await asyncio.to_thread(self._append, chat_id, role, content)

    async def recent(
        self, chat_id: str, *, exchanges: int = 5
    ) -> Sequence[ChatMessage]:
        return await asyncio.to_thread(self._recent, chat_id, exchanges)

    async def clear(self, chat_id: str) -> None:
        await asyncio.to_thread(self._clear, chat_id)

    def _append(
        self, chat_id: str, role: Literal["user", "assistant"], content: str
    ) -> None:
        with closing(self._database.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO conversation_messages (
                        chat_id, role, content, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        role,
                        content,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM conversation_messages
                    WHERE chat_id = ?
                      AND id NOT IN (
                          SELECT id FROM conversation_messages
                          WHERE chat_id = ?
                          ORDER BY id DESC
                          LIMIT ?
                      )
                    """,
                    (chat_id, chat_id, self._MAX_ROWS),
                )

    def _recent(self, chat_id: str, exchanges: int) -> Sequence[ChatMessage]:
        limit = 2 * max(exchanges, 1)
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return tuple(
            ChatMessage(role=row["role"], content=row["content"])
            for row in reversed(rows)
        )

    def _clear(self, chat_id: str) -> None:
        with closing(self._database.connect()) as connection:
            with connection:
                connection.execute(
                    "DELETE FROM conversation_messages WHERE chat_id = ?",
                    (chat_id,),
                )


class SqlitePluggyItemRepository:
    """Persists the known Pluggy items (one per connected bank)."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def upsert(self, item: PluggyItem) -> None:
        await asyncio.to_thread(self._upsert, item)

    async def list_active(self) -> Sequence[PluggyItem]:
        return await asyncio.to_thread(self._list_active)

    def _upsert(self, item: PluggyItem) -> None:
        updated_at = item.updated_at.isoformat()
        with closing(self._database.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO pluggy_items (
                        item_id, status, error, connector_name,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        status = excluded.status,
                        error = excluded.error,
                        connector_name = COALESCE(
                            excluded.connector_name,
                            pluggy_items.connector_name
                        ),
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(item.id),
                        item.status,
                        item.error,
                        item.connector_name,
                        updated_at,
                        updated_at,
                    ),
                )

    def _list_active(self) -> Sequence[PluggyItem]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT item_id, status, error, connector_name, updated_at
                FROM pluggy_items
                WHERE status != 'error'
                ORDER BY updated_at DESC, rowid DESC
                """
            ).fetchall()
        return tuple(self._row_to_item(row) for row in rows)

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> PluggyItem:
        return PluggyItem(
            id=UUID(row["item_id"]),
            status=row["status"],
            error=row["error"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
            connector_name=row["connector_name"],
        )


class SqliteBankingRepository:
    """Persists bank accounts, transactions and identity rows in SQLite."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    async def save_accounts(self, accounts: Sequence[BankAccount]) -> None:
        await asyncio.to_thread(self._save_accounts, accounts)

    async def save_transactions(
        self, transactions: Sequence[BankTransaction]
    ) -> None:
        await asyncio.to_thread(self._save_transactions, transactions)

    async def save_identity(self, identity: BankIdentity) -> None:
        await asyncio.to_thread(self._save_identity, identity)

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]:
        return await asyncio.to_thread(self._list_accounts, item_id)

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]:
        return await asyncio.to_thread(
            self._list_transactions, account_id, start, end
        )

    def _save_accounts(self, accounts: Sequence[BankAccount]) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with closing(self._database.connect()) as connection:
            with connection:
                for account in accounts:
                    connection.execute(
                        """
                        INSERT INTO pluggy_accounts (
                            account_id, item_id, type, name,
                            balance_cents, currency, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(account_id) DO UPDATE SET
                            item_id = excluded.item_id,
                            type = excluded.type,
                            name = excluded.name,
                            balance_cents = excluded.balance_cents,
                            currency = excluded.currency,
                            updated_at = excluded.updated_at
                        """,
                        (
                            str(account.id),
                            str(account.item_id),
                            account.type,
                            account.name,
                            account.balance_cents,
                            account.currency,
                            updated_at,
                        ),
                    )

    def _save_transactions(
        self, transactions: Sequence[BankTransaction]
    ) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with closing(self._database.connect()) as connection:
            with connection:
                for transaction in transactions:
                    connection.execute(
                        """
                        INSERT INTO pluggy_transactions (
                            transaction_id, account_id, item_id, entry_date,
                            description, amount_cents, currency, category,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(transaction_id) DO UPDATE SET
                            account_id = excluded.account_id,
                            item_id = excluded.item_id,
                            entry_date = excluded.entry_date,
                            description = excluded.description,
                            amount_cents = excluded.amount_cents,
                            currency = excluded.currency,
                            category = excluded.category,
                            updated_at = excluded.updated_at
                        """,
                        (
                            str(transaction.id),
                            str(transaction.account_id),
                            str(transaction.item_id),
                            transaction.day.isoformat(),
                            transaction.description,
                            transaction.amount_cents,
                            transaction.currency,
                            transaction.category,
                            updated_at,
                        ),
                    )

    def _save_identity(self, identity: BankIdentity) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with closing(self._database.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO pluggy_identity (
                        item_id, full_name, document, document_type,
                        birth_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        full_name = excluded.full_name,
                        document = excluded.document,
                        document_type = excluded.document_type,
                        birth_date = excluded.birth_date,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(identity.item_id),
                        identity.full_name,
                        identity.document,
                        identity.document_type,
                        identity.birth_date,
                        updated_at,
                    ),
                )

    def _list_accounts(self, item_id: UUID) -> Sequence[BankAccount]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT account_id, item_id, type, name,
                       balance_cents, currency
                FROM pluggy_accounts
                WHERE item_id = ?
                ORDER BY rowid
                """,
                (str(item_id),),
            ).fetchall()
        return tuple(self._row_to_account(row) for row in rows)

    def _list_transactions(
        self, account_id: UUID, start: date, end: date
    ) -> Sequence[BankTransaction]:
        with closing(self._database.connect()) as connection:
            rows = connection.execute(
                """
                SELECT transaction_id, account_id, item_id, entry_date,
                       description, amount_cents, currency, category
                FROM pluggy_transactions
                WHERE account_id = ?
                  AND entry_date >= ?
                  AND entry_date <= ?
                ORDER BY entry_date, rowid
                """,
                (str(account_id), start.isoformat(), end.isoformat()),
            ).fetchall()
        return tuple(self._row_to_transaction(row) for row in rows)

    @staticmethod
    def _row_to_account(row: sqlite3.Row) -> BankAccount:
        return BankAccount(
            id=UUID(row["account_id"]),
            item_id=UUID(row["item_id"]),
            type=row["type"],
            name=row["name"],
            balance_cents=row["balance_cents"],
            currency=row["currency"],
        )

    @staticmethod
    def _row_to_transaction(row: sqlite3.Row) -> BankTransaction:
        return BankTransaction(
            id=UUID(row["transaction_id"]),
            account_id=UUID(row["account_id"]),
            item_id=UUID(row["item_id"]),
            day=date.fromisoformat(row["entry_date"]),
            description=row["description"],
            amount_cents=row["amount_cents"],
            currency=row["currency"],
            category=row["category"],
        )
