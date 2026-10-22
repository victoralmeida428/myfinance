"""Ports the application depends on, implemented by infrastructure."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from myfinance.application.dto import ParsedMessage, SpendingQuery
from myfinance.domain.banking import (
    BankAccount,
    BankExpense,
    BankIdentity,
    BankTransaction,
    BankingIntent,
    PluggyItem,
)
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry
from myfinance.domain.models import ChatMessage, ClientUserId, ConnectToken

__all__ = [
    "BankExpenseProvider",
    "BankingProvider",
    "BankingRepository",
    "CategoryClassifier",
    "Clock",
    "ConnectTokenProvider",
    "ConversationMemory",
    "DateReferenceExtractor",
    "DateResolver",
    "EntryRepository",
    "FollowUpResolver",
    "IntentRouter",
    "LanguageModel",
    "LLMGate",
    "MessageParser",
    "PluggyItemRepository",
    "ProcessedUpdateRepository",
    "SpendingQueryParser",
    "SummaryIntentGate",
]


class CategoryClassifier(Protocol):
    """Maps a free-form message to an expense category, or abstains."""

    async def classify(self, text: str) -> Category | None: ...


class ConnectTokenProvider(Protocol):
    """Creates connect tokens for the payments provider."""

    async def create_connect_token(
        self, client_user_id: ClientUserId
    ) -> ConnectToken: ...


class LanguageModel(Protocol):
    """Completes a chat conversation and returns the assistant text."""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str: ...


class ConversationMemory(Protocol):
    """Stores the recent exchanges of a chat and reloads them in order."""

    async def append(
        self,
        chat_id: str,
        role: Literal["user", "assistant"],
        content: str,
    ) -> None: ...

    async def recent(
        self, chat_id: str, *, exchanges: int = 5
    ) -> Sequence[ChatMessage]: ...

    async def clear(self, chat_id: str) -> None: ...


class FollowUpResolver(Protocol):
    """Rewrites an elliptical follow-up into a standalone question."""

    async def rewrite(
        self, text: str, history: Sequence[ChatMessage]
    ) -> str | None: ...


class EntryRepository(Protocol):
    """Stores financial entries and reloads them by day or range."""

    async def add(self, entry: Entry) -> None: ...

    async def list_by_day(self, day: date) -> Sequence[Entry]: ...

    async def list_between(self, start: date, end: date) -> Sequence[Entry]: ...


class LLMGate(Protocol):
    """Decides whether an unparsed message should reach the LLM fallback.

    ``True`` means use the LLM, ``False`` means answer with the generic
    clarification, and ``None`` means the gate is unavailable so the caller
    should use its own heuristic.
    """

    async def should_use_llm(self, text: str) -> bool | None: ...


class SummaryIntentGate(Protocol):
    """Decides whether a message asks for a summary.

    ``True`` means a summary request, ``False`` means another kind of message,
    and ``None`` means the gate is unavailable so the caller should use its own
    heuristic.
    """

    async def should_summarize(self, text: str) -> bool | None: ...


class MessageParser(Protocol):
    """Extracts a structured entry from a free-form user message."""

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None: ...


class SpendingQueryParser(Protocol):
    """Extracts a spending query from a free-form user message."""

    async def parse(self, text: str, *, today: date) -> SpendingQuery | None: ...


class DateResolver(Protocol):
    """Turns a natural-language date reference into a concrete day."""

    def resolve(self, reference: str | None, *, today: date) -> date | None: ...


class DateReferenceExtractor(Protocol):
    """Finds the raw date reference inside a free-form sentence."""

    def extract(self, text: str) -> str | None: ...


class Clock(Protocol):
    """Supplies the current date and time."""

    def today(self) -> date: ...

    def now(self) -> datetime: ...


class ProcessedUpdateRepository(Protocol):
    """Tracks chat updates that have already been handled."""

    async def claim(self, update_id: int) -> bool: ...


class BankingProvider(Protocol):
    """Fetches bank data from the external provider (Pluggy)."""

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]: ...

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]: ...

    async def find_identity(self, item_id: UUID) -> BankIdentity | None: ...


class BankExpenseProvider(Protocol):
    """Fetches the real spends already posted to the connected banks."""

    async def expenses(
        self, start: date, end: date
    ) -> Sequence[BankExpense]: ...


class PluggyItemRepository(Protocol):
    """Stores the known Pluggy items (one per connected bank)."""

    async def upsert(self, item: PluggyItem) -> None: ...

    async def list_active(self) -> Sequence[PluggyItem]: ...


class BankingRepository(Protocol):
    """Stores and reloads bank data collected from Pluggy."""

    async def save_accounts(self, accounts: Sequence[BankAccount]) -> None: ...

    async def save_transactions(
        self, transactions: Sequence[BankTransaction]
    ) -> None: ...

    async def save_identity(self, identity: BankIdentity) -> None: ...

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]: ...

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]: ...


class IntentRouter(Protocol):
    """Classifies a free-form message into a banking intent."""

    async def route(self, text: str) -> BankingIntent: ...
