"""Unit tests for the month-over-month spending comparison."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from myfinance.application.dto import (
    SpendingComparisonMessage,
    SpendingQuery,
)
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    CompareSpendingUseCase,
    SearchSpendingUseCase,
)
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.comparison import (
    OpenCodeSpendingComparisonNarrator,
)

TODAY = date(2026, 10, 24)
CREATED_AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
UBER_QUERY = SpendingQuery(None, None, ("uber",))


class FixedClock:
    def today(self) -> date:
        return TODAY

    def now(self) -> datetime:
        return CREATED_AT


class InMemoryEntryRepository:
    def __init__(self, entries: Sequence[Entry] = ()) -> None:
        self.entries = list(entries)

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class FakeBankExpenses:
    def __init__(self, expenses: Sequence[BankExpense] = ()) -> None:
        self._expenses = tuple(expenses)

    async def expenses(
        self, start: date, end: date
    ) -> tuple[BankExpense, ...]:
        return tuple(
            expense
            for expense in self._expenses
            if start <= expense.day <= end
        )


class FakeParser:
    def __init__(self, query: SpendingQuery | None) -> None:
        self._query = query

    async def parse(self, text: str, *, today: date) -> SpendingQuery | None:
        return self._query


class FakeReferences:
    def extract(self, text: str) -> str | None:
        return None


class FakeDates:
    def resolve(self, reference: str | None, *, today: date) -> date | None:
        return None


class FakeNarrator:
    def __init__(
        self,
        reply: str | None = "Narrativa da comparação.",
        *,
        error: Exception | None = None,
    ) -> None:
        self._reply = reply
        self._error = error
        self.calls: list[object] = []

    async def narrate(self, comparison):
        self.calls.append(comparison)
        if self._error is not None:
            raise self._error
        return self._reply


def make_entry(
    day: date,
    cents: int,
    description: str,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(cents),
        description=description,
        category=Category.TRANSPORTE,
        created_at=CREATED_AT,
    )


def make_bank_expense(day: date, cents: int, description: str) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description=description,
        amount_cents=cents,
        category=Category.TRANSPORTE,
        institution="Itaú",
    )


def build_comparison(
    *,
    entries: Sequence[Entry] = (),
    bank: Sequence[BankExpense] = (),
    query: SpendingQuery | None = UBER_QUERY,
    narrator: FakeNarrator | None = None,
) -> CompareSpendingUseCase:
    clock = FixedClock()
    search = SearchSpendingUseCase(
        InMemoryEntryRepository(entries),
        FakeBankExpenses(bank),
        clock,
        FakeReferences(),
        FakeDates(),
        FakeParser(query),
    )
    return CompareSpendingUseCase(search, clock, narrator)


async def test_compares_current_month_with_the_previous_one() -> None:
    bank = (
        make_bank_expense(date(2026, 10, 12), 33036, "Uber"),
        make_bank_expense(date(2026, 9, 5), 50000, "Uber"),
    )
    duplicate = make_entry(date(2026, 10, 12), 33036, "Uber")
    manual = make_entry(date(2026, 10, 10), 30000, "Uber")
    forecast = make_entry(
        date(2026, 10, 11), 99999, "Uber", kind=EntryKind.FORECAST
    )

    comparison = await build_comparison(
        entries=[duplicate, manual, forecast], bank=bank
    ).execute("quanto gastei com uber neste mês comparado ao mês passado?")

    assert comparison is not None
    assert (comparison.current_start, comparison.current_end) == (
        date(2026, 10, 1),
        TODAY,
    )
    assert (comparison.previous_start, comparison.previous_end) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert comparison.current_total_cents == 63036
    assert comparison.current_count == 2
    assert comparison.previous_total_cents == 50000
    assert comparison.previous_count == 1
    assert comparison.delta_cents == 13036
    assert comparison.delta_percent == 26


async def test_previous_month_zero_has_no_percentage() -> None:
    comparison = await build_comparison(
        bank=(make_bank_expense(date(2026, 10, 12), 3000, "Uber"),)
    ).execute("comparado ao mês passado")

    assert comparison is not None
    assert comparison.current_total_cents == 3000
    assert comparison.previous_total_cents == 0
    assert comparison.delta_cents == 3000
    assert comparison.delta_percent is None


async def test_message_without_a_subject_returns_none() -> None:
    comparison = await build_comparison(
        query=SpendingQuery(None, None, ())
    ).execute("comparado ao mês passado")

    assert comparison is None


async def test_narrator_receives_the_computed_comparison() -> None:
    narrator = FakeNarrator()
    comparison = await build_comparison(
        bank=(make_bank_expense(date(2026, 10, 12), 3000, "Uber"),),
        narrator=narrator,
    ).execute("comparado ao mês passado")

    assert comparison is not None
    assert comparison.narrative == "Narrativa da comparação."
    assert len(narrator.calls) == 1
    assert narrator.calls[0].narrative is None  # type: ignore[attr-defined]
    assert (
        narrator.calls[0].current_total_cents == 3000  # type: ignore[attr-defined]
    )


async def test_narrator_failure_keeps_the_deterministic_numbers() -> None:
    narrator = FakeNarrator(error=ProviderError("narrator down"))
    comparison = await build_comparison(
        bank=(make_bank_expense(date(2026, 10, 12), 3000, "Uber"),),
        narrator=narrator,
    ).execute("comparado ao mês passado")

    assert comparison is not None
    assert comparison.narrative is None
    assert comparison.current_total_cents == 3000


class FakeLanguageModel:
    def __init__(self, reply: str = "", *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[Any]] = []

    async def complete(
        self, messages: list[Any], *, session_id: str | None = None
    ) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.reply


def comparison_message() -> SpendingComparisonMessage:
    return SpendingComparisonMessage(
        label="uber",
        current_start=date(2026, 10, 1),
        current_end=TODAY,
        current_total_cents=63036,
        current_count=32,
        previous_start=date(2026, 9, 1),
        previous_end=date(2026, 9, 30),
        previous_total_cents=50000,
        previous_count=25,
        delta_cents=13036,
        delta_percent=26,
    )


async def test_narrator_returns_the_trimmed_model_answer() -> None:
    narrator = OpenCodeSpendingComparisonNarrator(
        FakeLanguageModel("  Você gastou mais com uber.  ")
    )

    narrative = await narrator.narrate(comparison_message())

    assert narrative == "Você gastou mais com uber."


async def test_narrator_prompt_carries_the_computed_numbers() -> None:
    model = FakeLanguageModel("narrativa")
    narrator = OpenCodeSpendingComparisonNarrator(model)

    await narrator.narrate(comparison_message())

    payload = json.loads(model.calls[0][1].content)
    assert payload["label"] == "uber"
    assert payload["current_period"]["total_cents"] == 63036
    assert payload["previous_period"]["total_cents"] == 50000
    assert payload["delta_cents"] == 13036
    assert payload["delta_percent"] == 26
