"""Insights over realized spending."""

from __future__ import annotations

from datetime import date, timedelta

from myfinance.application.dto import MonthlyExpense, TopMonthMessage
from myfinance.application.ports import (
    BankExpenseProvider,
    Clock,
    EntryRepository,
)
from myfinance.domain.expenses import manual_expenses_not_in_bank
from myfinance.domain.summary import build_period_summary

__all__ = ["GetTopSpendingMonthUseCase"]


def _shift_month(first_day: date, delta: int) -> date:
    """Return the first day of the calendar month ``delta`` months away."""
    index = first_day.year * 12 + (first_day.month - 1) + delta
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


class GetTopSpendingMonthUseCase:
    """Rank the last months by realized spending and return the top month."""

    def __init__(
        self,
        repository: EntryRepository,
        bank_expenses: BankExpenseProvider,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._bank_expenses = bank_expenses
        self._clock = clock

    async def execute(self, months: int = 12) -> TopMonthMessage:
        today = self._clock.today()
        start = _shift_month(today.replace(day=1), -(months - 1))
        entries = await self._repository.list_between(start, today)
        bank = await self._bank_expenses.expenses(start, today)

        totals: dict[tuple[int, int], int] = {}
        for entry in manual_expenses_not_in_bank(entries, bank):
            key = (entry.day.year, entry.day.month)
            totals[key] = totals.get(key, 0) + entry.amount.cents
        for expense in bank:
            key = (expense.day.year, expense.day.month)
            totals[key] = totals.get(key, 0) + expense.amount_cents

        ranking = tuple(
            MonthlyExpense(
                year=year, month=month, expense_cents=expense_cents
            )
            for (year, month), expense_cents in sorted(
                totals.items(), key=lambda item: (-item[1], item[0])
            )
            if expense_cents > 0
        )[:3]

        if not ranking:
            return TopMonthMessage(
                window_start=start,
                window_end=today,
                ranking=(),
                winner_balances=(),
            )

        winner = ranking[0]
        month_start = date(winner.year, winner.month, 1)
        next_month_start = _shift_month(month_start, 1)
        is_current_month = (
            winner.year == today.year and winner.month == today.month
        )
        month_end = (
            today
            if is_current_month
            else next_month_start - timedelta(days=1)
        )
        summary = build_period_summary(
            month_start,
            month_end,
            tuple(
                entry
                for entry in entries
                if month_start <= entry.day <= month_end
            ),
            tuple(
                expense
                for expense in bank
                if month_start <= expense.day <= month_end
            ),
        )
        return TopMonthMessage(
            window_start=start,
            window_end=today,
            ranking=ranking,
            winner_balances=summary.balances,
        )
