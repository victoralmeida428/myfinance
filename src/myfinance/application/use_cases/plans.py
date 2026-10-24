"""Grounded spending-plan use case."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from myfinance.application.dto import (
    CategoryPlan,
    MerchantSpend,
    SpendingPlanMessage,
)
from myfinance.application.errors import ProviderError
from myfinance.application.periods import resolve_period
from myfinance.application.ports import (
    BankExpenseProvider,
    Clock,
    EntryRepository,
    SpendingPlanNarrator,
)
from myfinance.application.use_cases.plan_math import (
    DISCRETIONARY_CATEGORIES,
    clean_merchant,
    delta_percent,
    distribute_cuts,
    expense_items,
)
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category

__all__ = ["GetSpendingPlanUseCase"]


class GetSpendingPlanUseCase:
    """Build a grounded savings plan from the last analyzed spending window."""

    def __init__(
        self,
        entries: EntryRepository,
        bank_expenses: BankExpenseProvider | None,
        clock: Clock,
        narrator: SpendingPlanNarrator | None = None,
    ) -> None:
        self._entries = entries
        self._bank_expenses = bank_expenses
        self._clock = clock
        self._narrator = narrator

    async def execute(self, text: str = "") -> SpendingPlanMessage:
        today = self._clock.today()
        period = resolve_period(text, today=today) if text.strip() else None
        if period is None:
            last_day = today.replace(day=1) - timedelta(days=1)
            start = last_day.replace(day=1)
            end = last_day
        else:
            start, end = period

        length = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous_start = start - timedelta(days=length)

        entries = await self._entries.list_between(start, end)
        previous_entries = await self._entries.list_between(
            previous_start, previous_end
        )
        bank_expenses: Sequence[BankExpense] = ()
        previous_bank_expenses: Sequence[BankExpense] = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)
            previous_bank_expenses = await self._bank_expenses.expenses(
                previous_start, previous_end
            )

        items = expense_items(entries, bank_expenses)
        previous_items = expense_items(previous_entries, previous_bank_expenses)

        category_totals: dict[Category, int] = {}
        for _, cents, category, _ in items:
            category_totals[category] = category_totals.get(category, 0) + cents
        previous_totals: dict[Category, int] = {}
        for _, cents, category, _ in previous_items:
            previous_totals[category] = previous_totals.get(category, 0) + cents

        total_cents = sum(category_totals.values())
        previous_total_cents = sum(previous_totals.values())

        categories = tuple(
            CategoryPlan(
                category=category,
                total_cents=cents,
                share_percent=(
                    round(cents * 100 / total_cents) if total_cents else 0
                ),
                previous_cents=previous_totals.get(category, 0),
                delta_percent=delta_percent(
                    cents, previous_totals.get(category, 0)
                ),
            )
            for category, cents in sorted(
                category_totals.items(),
                key=lambda item: (-item[1], item[0].value),
            )
        )

        grouped: dict[str, list[int]] = {}
        for _, cents, _, description in items:
            name = clean_merchant(description)
            if not name:
                continue
            bucket = grouped.setdefault(name, [0, 0])
            bucket[0] += cents
            bucket[1] += 1
        merchants = tuple(
            MerchantSpend(name=name, total_cents=total, count=count)
            for name, (total, count) in sorted(
                grouped.items(), key=lambda item: (-item[1][0], item[0])
            )[:5]
        )

        target_cents = round(total_cents * 10 / 100)
        discretionary = sorted(
            (
                (category, cents)
                for category, cents in category_totals.items()
                if category in DISCRETIONARY_CATEGORIES and cents > 0
            ),
            key=lambda item: (-item[1], item[0].value),
        )[:3]
        cuts = distribute_cuts(discretionary, target_cents)

        plan = SpendingPlanMessage(
            start=start,
            end=end,
            total_cents=total_cents,
            count=len(items),
            previous_total_cents=previous_total_cents,
            categories=categories,
            merchants=merchants,
            target_cents=target_cents,
            cuts=cuts,
            narrative=None,
        )
        if self._narrator is None:
            return plan
        try:
            narrative = await self._narrator.narrate(plan)
        except ProviderError:
            narrative = None
        return replace(plan, narrative=narrative)
