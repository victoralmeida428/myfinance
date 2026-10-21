"""Unit tests for the SQLite persistence adapters."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.sqlite import (
    SqliteDatabase,
    SqliteEntryRepository,
    SqliteProcessedUpdateRepository,
)

DAY = date(2026, 10, 20)
OTHER_DAY = date(2026, 10, 21)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def make_entry(
    *,
    day: date = DAY,
    created_at: datetime = CREATED_AT,
    entry_id: UUID | None = None,
    description: str = "lançamento",
) -> Entry:
    return Entry(
        id=entry_id or uuid4(),
        kind=EntryKind.EXPENSE,
        day=day,
        amount=Money(4500),
        description=description,
        category=Category.ALIMENTACAO,
        created_at=created_at,
    )


def build_repository(path: Path) -> tuple[SqliteDatabase, SqliteEntryRepository]:
    database = SqliteDatabase(path)
    return database, SqliteEntryRepository(database)


async def test_add_and_list_by_day_return_only_that_day(
    tmp_path: Path,
) -> None:
    _database, repository = build_repository(tmp_path / "test.db")
    today_entry = make_entry()
    other_entry = make_entry(day=OTHER_DAY)

    await repository.add(today_entry)
    await repository.add(other_entry)

    entries = await repository.list_by_day(DAY)
    assert [entry.id for entry in entries] == [today_entry.id]
    assert entries[0].amount.cents == 4500
    assert entries[0].category is Category.ALIMENTACAO


async def test_duplicate_id_raises_integrity_error(tmp_path: Path) -> None:
    _database, repository = build_repository(tmp_path / "test.db")
    entry = make_entry()
    await repository.add(entry)

    with pytest.raises(sqlite3.IntegrityError):
        await repository.add(entry)


async def test_processed_update_can_only_be_claimed_once(
    tmp_path: Path,
) -> None:
    database = SqliteDatabase(tmp_path / "test.db")
    repository = SqliteProcessedUpdateRepository(database)

    assert await repository.claim(1) is True
    assert await repository.claim(1) is False


async def test_identical_created_at_keeps_insertion_order(
    tmp_path: Path,
) -> None:
    _database, repository = build_repository(tmp_path / "test.db")
    first = make_entry(description="primeiro")
    second = make_entry(description="segundo")

    await repository.add(first)
    await repository.add(second)

    entries = await repository.list_by_day(DAY)
    assert [entry.id for entry in entries] == [first.id, second.id]


async def test_schema_is_created_and_data_survives_reopening(
    tmp_path: Path,
) -> None:
    path = tmp_path / "test.db"
    _database, repository = build_repository(path)
    entry = make_entry()
    await repository.add(entry)

    _reopened, reopened_repository = build_repository(path)

    entries = await reopened_repository.list_by_day(DAY)
    assert [stored.id for stored in entries] == [entry.id]
