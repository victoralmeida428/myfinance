"""Unit tests for daily reconciliation of forecasts against expenses."""

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import BalanceStatus, build_daily_summary

DAY = date(2026, 10, 20)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def make_entry(
    kind: EntryKind,
    cents: int,
    category: Category,
    *,
    description: str = "lançamento",
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=DAY,
        amount=Money(cents),
        description=description,
        category=category,
        created_at=CREATED_AT,
    )


def test_forecast_and_expense_within_budget_are_ok() -> None:
    summary = build_daily_summary(
        DAY,
        [
            make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
            make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO),
        ],
    )

    balance = summary.balances[0]
    assert balance.forecast_cents == 8000
    assert balance.expense_cents == 4500
    assert balance.difference_cents == 3500
    assert balance.status is BalanceStatus.OK


def test_expense_above_forecast_is_over() -> None:
    summary = build_daily_summary(
        DAY,
        [
            make_entry(EntryKind.FORECAST, 3000, Category.TRANSPORTE),
            make_entry(EntryKind.EXPENSE, 4500, Category.TRANSPORTE),
        ],
    )

    balance = summary.balances[0]
    assert balance.status is BalanceStatus.OVER
    assert balance.difference_cents == -1500


def test_expense_without_forecast_is_unplanned() -> None:
    summary = build_daily_summary(
        DAY,
        [make_entry(EntryKind.EXPENSE, 6000, Category.LAZER)],
    )

    balance = summary.balances[0]
    assert balance.forecast_cents == 0
    assert balance.expense_cents == 6000
    assert balance.status is BalanceStatus.UNPLANNED


def test_entries_are_grouped_by_category_and_totalled() -> None:
    summary = build_daily_summary(
        DAY,
        [
            make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
            make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO),
            make_entry(EntryKind.FORECAST, 2000, Category.TRANSPORTE),
            make_entry(EntryKind.EXPENSE, 2500, Category.TRANSPORTE),
        ],
    )

    alimentacao, transporte = summary.balances
    assert alimentacao.forecast_cents == 8000
    assert alimentacao.expense_cents == 4500
    assert transporte.forecast_cents == 2000
    assert transporte.expense_cents == 2500
    assert transporte.status is BalanceStatus.OVER
    assert summary.total_forecast_cents == 10000
    assert summary.total_expense_cents == 7000
    assert summary.total_difference_cents == 3000
    assert summary.has_deficit is False


def test_has_deficit_when_expenses_exceed_all_forecasts() -> None:
    summary = build_daily_summary(
        DAY,
        [
            make_entry(EntryKind.FORECAST, 3000, Category.ALIMENTACAO),
            make_entry(EntryKind.EXPENSE, 5000, Category.ALIMENTACAO),
        ],
    )

    assert summary.has_deficit is True
    assert summary.total_difference_cents == -2000


def test_inactive_categories_are_omitted_and_order_follows_declaration() -> None:
    summary = build_daily_summary(
        DAY,
        [
            make_entry(EntryKind.EXPENSE, 1000, Category.LAZER),
            make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
            make_entry(EntryKind.EXPENSE, 2000, Category.TRANSPORTE),
        ],
    )

    assert [balance.category for balance in summary.balances] == [
        Category.ALIMENTACAO,
        Category.TRANSPORTE,
        Category.LAZER,
    ]
    assert Category.SAUDE not in {balance.category for balance in summary.balances}
    assert Category.SERVICOS not in {
        balance.category for balance in summary.balances
    }
