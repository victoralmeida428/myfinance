"""Free-form spending search."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from myfinance.application.dto import SpendingAnswerMessage, SpendingQuery
from myfinance.application.periods import resolve_period
from myfinance.application.ports import (
    BankExpenseProvider,
    Clock,
    DateReferenceExtractor,
    DateResolver,
    EntryRepository,
    SpendingQueryParser,
)
from myfinance.application.use_cases.common import strip_accents
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.expenses import manual_expenses_not_in_bank

__all__ = ["SearchSpendingUseCase"]


class SearchSpendingUseCase:
    """Answer a free-form spending question over manual entries and the bank.

    Provider failures propagate so callers can explain them instead of
    rendering an empty answer.
    """

    def __init__(
        self,
        entries: EntryRepository,
        bank_expenses: BankExpenseProvider | None,
        clock: Clock,
        references: DateReferenceExtractor,
        dates: DateResolver,
        parser: SpendingQueryParser,
    ) -> None:
        self._entries = entries
        self._bank_expenses = bank_expenses
        self._clock = clock
        self._references = references
        self._dates = dates
        self._parser = parser

    async def execute(self, text: str) -> SpendingAnswerMessage | None:
        today = self._clock.today()
        query = await self._parser.parse(text, today=today)
        if query is None:
            return None

        start, end = self._resolve_period(
            query.period_reference or text, text, today
        )
        entries = await self._entries.list_between(start, end)
        bank_expenses: Sequence[BankExpense] = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)

        amounts: list[int] = []
        for entry in manual_expenses_not_in_bank(entries, bank_expenses):
            if self._matches(
                query,
                entry.category,
                (entry.description, entry.category.label, entry.category.value),
            ):
                amounts.append(entry.amount.cents)
        for expense in bank_expenses:
            if self._matches(
                query,
                expense.category,
                (
                    expense.description,
                    expense.category.label,
                    expense.category.value,
                    expense.raw_category or "",
                    expense.description_raw or "",
                ),
            ):
                amounts.append(expense.amount_cents)

        label = (
            query.category.label
            if query.category is not None
            else ", ".join(query.keywords)
        )
        return SpendingAnswerMessage(
            start=start,
            end=end,
            label=label,
            total_cents=sum(amounts),
            count=len(amounts),
            category=query.category,
            keywords=query.keywords,
        )

    def _resolve_period(
        self, reference: str, text: str, today: date
    ) -> tuple[date, date]:
        period = resolve_period(reference, today=today)
        if period is not None:
            return period
        extracted = self._references.extract(text)
        if extracted is not None:
            day = self._dates.resolve(extracted, today=today)
            if day is not None:
                return day, day
        return today.replace(day=1), today

    @staticmethod
    def _matches(
        query: SpendingQuery, item_category: Category, parts: Sequence[str]
    ) -> bool:
        if query.category is not None and item_category is query.category:
            return True
        haystack = strip_accents(" ".join(parts))
        return any(
            strip_accents(keyword) in haystack
            for keyword in query.keywords
            if keyword.strip()
        )
