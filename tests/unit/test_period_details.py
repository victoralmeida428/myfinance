"""Unit tests for period details and their Telegram rendering."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.application.use_cases import GetPeriodDetailsUseCase
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.presentation.telegram.formatting import format_period_details

TODAY = date(2026, 10, 22)
CREATED_AT = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


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


def make_entry(
    day: date,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
    amount_cents: int = 4500,
    description: str = "almoço",
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(amount_cents),
        description=description,
        category=Category.ALIMENTACAO,
        created_at=CREATED_AT,
    )


def make_bank_expense(
    day: date,
    *,
    amount_cents: int = 3000,
    description: str = "uber",
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description=description,
        amount_cents=amount_cents,
        category=Category.TRANSPORTE,
        institution="Itaú",
    )


def build_use_case(
    entries: Sequence[Entry] = (),
    bank_expenses: Sequence[BankExpense] = (),
) -> GetPeriodDetailsUseCase:
    return GetPeriodDetailsUseCase(
        InMemoryEntryRepository(entries),
        FakeBankExpenses(bank_expenses),
        FixedClock(),
        PortugueseDateReferenceExtractor(),
        PortugueseDateResolver(),
    )


async def test_month_reference_collects_manual_and_bank_entries() -> None:
    duplicate = make_entry(date(2026, 9, 10), amount_cents=3000)
    manual = make_entry(date(2026, 9, 3), description="mercado")
    bank = make_bank_expense(date(2026, 9, 10))

    details = await build_use_case(
        [duplicate, manual], [bank]
    ).execute("lançamentos do mês de set/2026")

    assert (details.start, details.end) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert [(item.day, item.description, item.from_bank) for item in details.items] == [
        (date(2026, 9, 3), "mercado", False),
        (date(2026, 9, 10), "uber", True),
    ]


async def test_forecasts_are_not_listed() -> None:
    forecast = make_entry(date(2026, 9, 5), kind=EntryKind.FORECAST)

    details = await build_use_case([forecast]).execute("setembro de 2026")

    assert details.items == ()


async def test_empty_period_has_no_items() -> None:
    details = await build_use_case().execute("set/2026")

    assert details.items == ()


async def test_format_period_details_lists_and_totals_items() -> None:
    manual = make_entry(date(2026, 9, 3), amount_cents=4500)
    bank = make_bank_expense(date(2026, 9, 10), amount_cents=3000)

    text = format_period_details(
        await build_use_case([manual], [bank]).execute("set/2026")
    )

    assert "Lançamentos de 01/09/2026 a 30/09/2026" in text
    assert "03/09 Alimentação: R$ 45,00 (almoço)" in text
    assert "10/09 Transporte (banco): R$ 30,00 (uber)" in text
    assert "Total: R$ 75,00 (2 lançamentos)" in text


async def test_format_period_details_explains_an_empty_period() -> None:
    text = format_period_details(
        await build_use_case().execute("set/2026")
    )

    assert text == "Nenhum lançamento de 01/09/2026 a 30/09/2026."
