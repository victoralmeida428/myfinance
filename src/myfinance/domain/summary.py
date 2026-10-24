"""Daily reconciliation of forecasts against expenses."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.expenses import manual_expenses_not_in_bank

__all__ = [
    "BalanceStatus",
    "CategoryBalance",
    "DailySummary",
    "PeriodSummary",
    "build_daily_summary",
    "build_period_summary",
]


class BalanceStatus(StrEnum):
    """How a category's expenses compare with its forecast."""

    OK = "ok"
    OVER = "over"
    UNPLANNED = "unplanned"


@dataclass(frozen=True, slots=True)
class CategoryBalance:
    """Forecast and expense totals for one category."""

    category: Category
    forecast_cents: int
    expense_cents: int
    manual_expense_cents: int = 0
    bank_expense_cents: int = 0

    @property
    def difference_cents(self) -> int:
        """Return how much of the forecast remains (negative when over)."""
        return self.forecast_cents - self.expense_cents

    @property
    def status(self) -> BalanceStatus:
        """Classify the category against its forecast."""
        if self.forecast_cents == 0 and self.expense_cents > 0:
            return BalanceStatus.UNPLANNED
        if self.forecast_cents > 0 and self.expense_cents > self.forecast_cents:
            return BalanceStatus.OVER
        return BalanceStatus.OK


@dataclass(frozen=True, slots=True)
class DailySummary:
    """All category balances for a single day."""

    day: date
    balances: tuple[CategoryBalance, ...]

    @property
    def total_forecast_cents(self) -> int:
        """Return the sum of every forecast."""
        return sum(balance.forecast_cents for balance in self.balances)

    @property
    def total_expense_cents(self) -> int:
        """Return the sum of every expense."""
        return sum(balance.expense_cents for balance in self.balances)

    @property
    def total_difference_cents(self) -> int:
        """Return the remaining forecast for the whole day."""
        return self.total_forecast_cents - self.total_expense_cents

    @property
    def has_deficit(self) -> bool:
        """Return whether expenses exceed forecasts for the day."""
        return self.total_expense_cents > self.total_forecast_cents


def build_daily_summary(
    day: date,
    entries: Sequence[Entry],
    bank_expenses: Sequence[BankExpense] = (),
) -> DailySummary:
    """Aggregate ``entries`` and ``bank_expenses`` into a :class:`DailySummary`.

    Manual expenses that already appear in the bank feed (same day and amount)
    are ignored so the same spend is not counted twice. Only categories with a
    forecast or an expense are included, and they are ordered by the
    declaration order of :class:`Category`.
    """
    return DailySummary(
        day=day, balances=_build_balances(entries, bank_expenses)
    )


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    """All category balances for an inclusive range of days."""

    start: date
    end: date
    balances: tuple[CategoryBalance, ...]

    @property
    def total_forecast_cents(self) -> int:
        """Return the sum of every forecast."""
        return sum(balance.forecast_cents for balance in self.balances)

    @property
    def total_expense_cents(self) -> int:
        """Return the sum of every expense."""
        return sum(balance.expense_cents for balance in self.balances)

    @property
    def total_difference_cents(self) -> int:
        """Return the remaining forecast for the whole period."""
        return self.total_forecast_cents - self.total_expense_cents

    @property
    def has_deficit(self) -> bool:
        """Return whether expenses exceed forecasts for the period."""
        return self.total_expense_cents > self.total_forecast_cents


def build_period_summary(
    start: date,
    end: date,
    entries: Sequence[Entry],
    bank_expenses: Sequence[BankExpense] = (),
) -> PeriodSummary:
    """Aggregate ``entries`` and ``bank_expenses`` into a :class:`PeriodSummary`.

    Every entry is expected to fall inside ``start``..``end``; the caller is
    responsible for selecting the window. Manual expenses already present in
    the bank feed are ignored, as in :func:`build_daily_summary`.
    """
    return PeriodSummary(
        start=start,
        end=end,
        balances=_build_balances(entries, bank_expenses),
    )


def _build_balances(
    entries: Sequence[Entry], bank_expenses: Sequence[BankExpense]
) -> tuple[CategoryBalance, ...]:
    """Group entries and bank expenses by category in declaration order."""
    forecast: dict[Category, int] = {}
    manual_expense: dict[Category, int] = {}
    bank_expense: dict[Category, int] = {}

    for entry in entries:
        if entry.kind is EntryKind.FORECAST:
            forecast[entry.category] = (
                forecast.get(entry.category, 0) + entry.amount.cents
            )

    for entry in manual_expenses_not_in_bank(entries, bank_expenses):
        manual_expense[entry.category] = (
            manual_expense.get(entry.category, 0) + entry.amount.cents
        )

    for expense in bank_expenses:
        bank_expense[expense.category] = (
            bank_expense.get(expense.category, 0) + expense.amount_cents
        )

    def total_expense(category: Category) -> int:
        return manual_expense.get(category, 0) + bank_expense.get(category, 0)

    return tuple(
        CategoryBalance(
            category=category,
            forecast_cents=forecast.get(category, 0),
            expense_cents=total_expense(category),
            manual_expense_cents=manual_expense.get(category, 0),
            bank_expense_cents=bank_expense.get(category, 0),
        )
        for category in Category
        if forecast.get(category, 0) > 0 or total_expense(category) > 0
    )
