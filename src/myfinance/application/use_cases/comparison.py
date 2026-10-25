"""Compare the current month with the previous one for a spending subject."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from myfinance.application.dto import SpendingComparisonMessage
from myfinance.application.errors import ProviderError
from myfinance.application.ports import Clock, SpendingComparisonNarrator
from myfinance.application.use_cases.spending import SearchSpendingUseCase

__all__ = ["CompareSpendingUseCase"]


class CompareSpendingUseCase:
    """Compare the current month with the previous month for one subject."""

    def __init__(
        self,
        search: SearchSpendingUseCase,
        clock: Clock,
        narrator: SpendingComparisonNarrator | None = None,
    ) -> None:
        self._search = search
        self._clock = clock
        self._narrator = narrator

    async def execute(self, text: str) -> SpendingComparisonMessage | None:
        query = await self._search.parse(text)
        if query is None:
            return None
        if query.category is None and not any(
            keyword.strip() for keyword in query.keywords
        ):
            return None

        today = self._clock.today()
        current_start = today.replace(day=1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)

        current_total, current_count = await self._search.summarize(
            query, current_start, today
        )
        previous_total, previous_count = await self._search.summarize(
            query, previous_start, previous_end
        )

        delta_cents = current_total - previous_total
        delta_percent = (
            round(delta_cents * 100 / previous_total)
            if previous_total > 0
            else None
        )
        label = (
            query.category.label
            if query.category is not None
            else ", ".join(query.keywords)
        )
        comparison = SpendingComparisonMessage(
            label=label,
            current_start=current_start,
            current_end=today,
            current_total_cents=current_total,
            current_count=current_count,
            previous_start=previous_start,
            previous_end=previous_end,
            previous_total_cents=previous_total,
            previous_count=previous_count,
            delta_cents=delta_cents,
            delta_percent=delta_percent,
        )
        if self._narrator is None:
            return comparison
        try:
            narrative = await self._narrator.narrate(comparison)
        except ProviderError:
            narrative = None
        return replace(comparison, narrative=narrative)
