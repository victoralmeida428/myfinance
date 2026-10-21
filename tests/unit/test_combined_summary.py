"""Unit tests for summaries that combine manual entries with bank expenses."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import build_daily_summary, build_period_summary

DAY = date(2026, 10, 20)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def make_entry(
    kind: EntryKind,
    cents: int,
    category: Category,
    *,
    day: date = DAY,
    description: str = "lançamento",
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(cents),
        description=description,
        category=category,
        created_at=CREATED_AT,
    )


def make_bank_expense(
    cents: int,
    category: Category,
    *,
    day: date = DAY,
    description: str = "compra no débito",
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description=description,
        amount_cents=cents,
        category=category,
        institution="Nubank",
    )


def test_manual_expense_matching_the_bank_is_deduplicated() -> None:
    entries = (
        make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO),
    )
    bank_expenses = (make_bank_expense(4500, Category.ALIMENTACAO),)

    summary = build_daily_summary(DAY, entries, bank_expenses)

    balance = summary.balances[0]
    assert balance.category is Category.ALIMENTACAO
    assert balance.expense_cents == 4500
    assert balance.manual_expense_cents == 0
    assert balance.bank_expense_cents == 4500


def test_bank_and_manual_expenses_in_the_same_category_are_added() -> None:
    entries = (make_entry(EntryKind.EXPENSE, 2000, Category.TRANSPORTE),)
    bank_expenses = (make_bank_expense(3000, Category.TRANSPORTE),)

    summary = build_daily_summary(DAY, entries, bank_expenses)

    balance = summary.balances[0]
    assert balance.expense_cents == 5000
    assert balance.manual_expense_cents == 2000
    assert balance.bank_expense_cents == 3000


def test_totals_and_deficit_include_bank_expenses() -> None:
    entries = (
        make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 2000, Category.TRANSPORTE),
    )
    bank_expenses = (
        make_bank_expense(4500, Category.ALIMENTACAO),
        make_bank_expense(3000, Category.TRANSPORTE),
    )

    summary = build_daily_summary(DAY, entries, bank_expenses)

    assert summary.total_forecast_cents == 8000
    assert summary.total_expense_cents == 9500
    assert summary.total_difference_cents == -1500
    assert summary.has_deficit is True


def test_only_categories_with_activity_are_kept_in_declaration_order() -> None:
    entries = (
        make_entry(EntryKind.FORECAST, 1000, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 500, Category.SERVICOS),
    )
    bank_expenses = (make_bank_expense(700, Category.LAZER),)

    summary = build_daily_summary(DAY, entries, bank_expenses)

    assert [balance.category for balance in summary.balances] == [
        Category.ALIMENTACAO,
        Category.LAZER,
        Category.SERVICOS,
    ]


def test_builders_still_work_without_bank_expenses() -> None:
    entries = (
        make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO, day=DAY),
        make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO, day=DAY),
    )

    daily = build_daily_summary(DAY, entries)
    period = build_period_summary(DAY, DAY, entries)

    assert daily.total_expense_cents == 4500
    assert daily.balances[0].manual_expense_cents == 4500
    assert daily.balances[0].bank_expense_cents == 0
    assert period.total_expense_cents == 4500


def test_period_summary_aggregates_bank_expenses_across_days() -> None:
    second_day = date(2026, 10, 21)
    entries = (
        make_entry(EntryKind.EXPENSE, 2000, Category.TRANSPORTE, day=DAY),
    )
    bank_expenses = (
        make_bank_expense(3000, Category.TRANSPORTE, day=DAY),
        make_bank_expense(1500, Category.TRANSPORTE, day=second_day),
    )

    summary = build_period_summary(DAY, second_day, entries, bank_expenses)

    balance = summary.balances[0]
    assert balance.expense_cents == 6500
    assert balance.manual_expense_cents == 2000
    assert balance.bank_expense_cents == 4500
