"""Calculation helpers for the spending-plan use case."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from myfinance.application.dto import CutSuggestion
from myfinance.application.use_cases.common import strip_accents
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry
from myfinance.domain.expenses import manual_expenses_not_in_bank

DISCRETIONARY_CATEGORIES = frozenset(
    {
        Category.ALIMENTACAO,
        Category.TRANSPORTE,
        Category.LAZER,
        Category.OUTROS,
    }
)

# Longest first, so "transferencia enviada pelo pix" wins over "pix".
_MERCHANT_PREFIXES = (
    "transferencia enviada pelo pix",
    "transferencia enviada",
    "compra no debito",
    "pagamento efetuado",
    "pagamento",
    "pix",
    "compra",
)


def delta_percent(current_cents: int, previous_cents: int) -> int | None:
    """Return the percentage change, or ``None`` without a previous base."""
    if previous_cents <= 0:
        return None
    return round((current_cents - previous_cents) * 100 / previous_cents)


def clean_merchant(description: str) -> str:
    """Strip bank transaction prefixes and normalise the merchant name."""
    text = description.strip()
    if "|" in text:
        head, _, tail = text.partition("|")
        if strip_accents(head).strip(" -") in _MERCHANT_PREFIXES:
            text = tail
    return strip_accents(text).strip(" -|")


def expense_items(
    entries: Sequence[Entry], bank_expenses: Sequence[BankExpense]
) -> list[tuple[date, int, Category, str]]:
    """Combine manual and bank spends, dropping forecasts and duplicates."""
    items: list[tuple[date, int, Category, str]] = [
        (entry.day, entry.amount.cents, entry.category, entry.description)
        for entry in manual_expenses_not_in_bank(entries, bank_expenses)
    ]
    for expense in bank_expenses:
        items.append(
            (
                expense.day,
                expense.amount_cents,
                expense.category,
                expense.description,
            )
        )
    return items


def distribute_cuts(
    categories: Sequence[tuple[Category, int]], target_cents: int
) -> tuple[CutSuggestion, ...]:
    """Split ``target_cents`` proportionally, forcing the sum to match it."""
    if not categories or target_cents <= 0:
        return ()
    total_cents = sum(cents for _, cents in categories)
    if total_cents <= 0:
        return ()

    cuts: list[CutSuggestion] = []
    allocated = 0
    for index, (category, cents) in enumerate(categories):
        is_last = index == len(categories) - 1
        cut_cents = (
            target_cents - allocated
            if is_last
            else round(target_cents * cents / total_cents)
        )
        allocated += cut_cents
        cuts.append(
            CutSuggestion(
                label=category.label,
                current_cents=cents,
                cut_cents=cut_cents,
            )
        )
    return tuple(cuts)
