"""Pluggy adapter that turns posted bank movements into real expenses.

Bank expenses are fetched on demand from Pluggy and never persisted: the
summary use cases are the only consumers. A movement only counts as an expense
when it is a ``DEBIT`` (this excludes bank inflows and credit-card payments,
which Pluggy reports as ``CREDIT``) and its raw category is not one of the
bookkeeping categories that would double count or misrepresent spending.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import date

from myfinance.application.ports import (
    BankingProvider,
    CategoryClassifier,
    PluggyItemRepository,
)
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category, coerce_category

__all__ = ["PluggyBankExpenseProvider"]

_EXCLUDED_CATEGORIES = frozenset(
    {
        "credit card payment",
        "transfers",
        "same person transfer",
        "investments",
    }
)

_CATEGORY_BY_RAW: dict[str, Category] = {
    "eating out": Category.ALIMENTACAO,
    "groceries": Category.ALIMENTACAO,
    "food delivery": Category.ALIMENTACAO,
    "taxi and ride-hailing": Category.TRANSPORTE,
    "gas stations": Category.TRANSPORTE,
    "public transportation": Category.TRANSPORTE,
    "parking": Category.TRANSPORTE,
    "leisure": Category.LAZER,
    "gaming": Category.LAZER,
    "sports goods": Category.LAZER,
    "bookstore": Category.LAZER,
    "pharmacy": Category.SAUDE,
    "health": Category.SAUDE,
    "services": Category.SERVICOS,
    "digital services": Category.SERVICOS,
    "telecommunications": Category.SERVICOS,
    "electricity": Category.SERVICOS,
    "internet": Category.SERVICOS,
    "housing": Category.SERVICOS,
    "bank fees": Category.SERVICOS,
    "shopping": Category.OUTROS,
    "online shopping": Category.OUTROS,
    "clothing": Category.OUTROS,
    "electronics": Category.OUTROS,
    "houseware": Category.OUTROS,
    "university": Category.OUTROS,
    "tax on financial operations": Category.OUTROS,
}


def _normalize(text: str | None) -> str:
    """Lowercase, remove accents and collapse whitespace in a raw category."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


class PluggyBankExpenseProvider:
    """Collects real spends from the connected banks through Pluggy."""

    def __init__(
        self,
        banking: BankingProvider,
        items: PluggyItemRepository,
        classifier: CategoryClassifier,
    ) -> None:
        self._banking = banking
        self._items = items
        self._classifier = classifier

    async def expenses(
        self, start: date, end: date
    ) -> Sequence[BankExpense]:
        items = await self._items.list_active()
        if not items:
            return ()

        expenses: list[BankExpense] = []
        for item in items:
            accounts = await self._banking.list_accounts(item.id)
            for account in accounts:
                transactions = await self._banking.list_transactions(
                    account.id, start=start, end=end
                )
                for transaction in transactions:
                    if transaction.direction != "DEBIT":
                        continue
                    raw_category = _normalize(transaction.category)
                    if raw_category in _EXCLUDED_CATEGORIES:
                        continue
                    category = await self._category(
                        raw_category, transaction.description
                    )
                    expenses.append(
                        BankExpense(
                            id=transaction.id,
                            day=transaction.day,
                            description=transaction.description,
                            amount_cents=abs(transaction.amount_cents),
                            category=coerce_category(category),
                            institution=item.connector_name,
                            raw_category=transaction.category,
                            description_raw=transaction.description_raw,
                        )
                    )
        return tuple(expenses)

    async def _category(
        self, raw_category: str, description: str
    ) -> Category:
        mapped = _CATEGORY_BY_RAW.get(raw_category)
        if mapped is not None:
            return mapped
        classified = await self._classifier.classify(description)
        return coerce_category(classified)
