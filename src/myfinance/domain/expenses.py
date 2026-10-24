"""Shared rules for reconciling manual entries with the bank feed."""

from __future__ import annotations

from collections.abc import Sequence

from myfinance.domain.banking import BankExpense
from myfinance.domain.entries import Entry, EntryKind

__all__ = ["manual_expenses_not_in_bank"]


def manual_expenses_not_in_bank(
    entries: Sequence[Entry],
    bank_expenses: Sequence[BankExpense],
) -> tuple[Entry, ...]:
    """Return manual expenses that are not already present in the bank feed.

    Forecasts are excluded. A manual expense is ignored when a bank expense
    shares both its day and its amount, so the same spend is never counted
    twice. The original order is preserved.
    """
    bank_keys = {
        (expense.day, expense.amount_cents) for expense in bank_expenses
    }
    return tuple(
        entry
        for entry in entries
        if entry.kind is not EntryKind.FORECAST
        and (entry.day, entry.amount.cents) not in bank_keys
    )
