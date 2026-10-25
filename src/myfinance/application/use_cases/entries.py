"""Registration and summary use cases for financial entries."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from myfinance.application.dto import (
    DayDetails,
    ParsedMessage,
    PeriodDetails,
    PeriodItem,
    RegistrationResult,
)
from myfinance.application.errors import InvalidDateReference
from myfinance.application.periods import resolve_period
from myfinance.application.ports import (
    BankExpenseProvider,
    Clock,
    DateReferenceExtractor,
    DateResolver,
    EntryRepository,
)
from myfinance.domain.entries import Entry
from myfinance.domain.expenses import manual_expenses_not_in_bank
from myfinance.domain.summary import (
    DailySummary,
    PeriodSummary,
    build_daily_summary,
    build_period_summary,
)

__all__ = [
    "GetDailySummaryUseCase",
    "GetDayDetailsUseCase",
    "GetPeriodDetailsUseCase",
    "GetPeriodSummaryUseCase",
    "GetSummaryUseCase",
    "RegisterEntryUseCase",
]


class RegisterEntryUseCase:
    """Persist a parsed entry and return the updated daily summary."""

    def __init__(self, repository: EntryRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def execute(self, parsed: ParsedMessage) -> RegistrationResult:
        entry = Entry(
            id=uuid4(),
            kind=parsed.kind,
            day=parsed.day,
            amount=parsed.amount,
            description=parsed.description,
            category=parsed.category,
            created_at=self._clock.now(),
        )
        await self._repository.add(entry)
        entries = await self._repository.list_by_day(parsed.day)
        summary = build_daily_summary(parsed.day, entries)
        return RegistrationResult(entry=entry, summary=summary)


class GetDailySummaryUseCase:
    """Return the daily summary for a referenced day.

    Provider failures propagate so callers can explain them instead of
    rendering an empty day.
    """

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        resolver: DateResolver,
        bank_expenses: BankExpenseProvider | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._resolver = resolver
        self._bank_expenses = bank_expenses

    async def execute(self, reference: str | None = None) -> DailySummary:
        day = self._resolve(reference)
        entries = await self._repository.list_by_day(day)
        bank_expenses = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(day, day)
        return build_daily_summary(day, entries, bank_expenses)

    def _resolve(self, reference: str | None) -> date:
        today = self._clock.today()
        day = self._resolver.resolve(reference, today=today)
        if day is None:
            raise InvalidDateReference("Não entendi a data informada.")
        return day


class GetPeriodSummaryUseCase:
    """Return the summary of the period named by a reference, when recognised.

    Provider failures propagate so callers can explain them instead of
    rendering an empty period.
    """

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        bank_expenses: BankExpenseProvider | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._bank_expenses = bank_expenses

    async def execute(self, reference: str | None) -> PeriodSummary | None:
        period = resolve_period(reference, today=self._clock.today())
        if period is None:
            return None
        start, end = period
        entries = await self._repository.list_between(start, end)
        bank_expenses = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)
        return build_period_summary(start, end, entries, bank_expenses)


class GetSummaryUseCase:
    """Return a period summary when the reference names one, else a day."""

    def __init__(
        self,
        period_summary: GetPeriodSummaryUseCase,
        daily_summary: GetDailySummaryUseCase,
    ) -> None:
        self._period_summary = period_summary
        self._daily_summary = daily_summary

    async def execute(
        self, reference: str | None = None
    ) -> DailySummary | PeriodSummary:
        period = await self._period_summary.execute(reference)
        if period is not None:
            return period
        return await self._daily_summary.execute(reference)


class GetDayDetailsUseCase:
    """Return the resolved day together with its entries."""

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        resolver: DateResolver,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._resolver = resolver

    async def execute(self, reference: str | None = None) -> DayDetails:
        today = self._clock.today()
        day = self._resolver.resolve(reference, today=today)
        if day is None:
            raise InvalidDateReference("Não entendi a data informada.")
        entries = await self._repository.list_by_day(day)
        return DayDetails(day=day, entries=entries)


class GetPeriodDetailsUseCase:
    """List the realized entries of a period, with bank spending included."""

    def __init__(
        self,
        repository: EntryRepository,
        bank_expenses: BankExpenseProvider | None,
        clock: Clock,
        references: DateReferenceExtractor,
        dates: DateResolver,
    ) -> None:
        self._repository = repository
        self._bank_expenses = bank_expenses
        self._clock = clock
        self._references = references
        self._dates = dates

    async def execute(self, reference: str | None = None) -> PeriodDetails:
        start, end = self._resolve_period(reference)
        entries = await self._repository.list_between(start, end)
        bank_expenses = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)

        items = [
            PeriodItem(
                day=entry.day,
                description=entry.description,
                category=entry.category,
                amount_cents=entry.amount.cents,
                from_bank=False,
            )
            for entry in manual_expenses_not_in_bank(entries, bank_expenses)
        ]
        items.extend(
            PeriodItem(
                day=expense.day,
                description=expense.description,
                category=expense.category,
                amount_cents=expense.amount_cents,
                from_bank=True,
            )
            for expense in bank_expenses
        )
        items.sort(key=lambda item: (item.day, item.description))
        return PeriodDetails(start=start, end=end, items=tuple(items))

    def _resolve_period(self, reference: str | None) -> tuple[date, date]:
        today = self._clock.today()
        if reference:
            period = resolve_period(reference, today=today)
            if period is not None:
                return period
            extracted = self._references.extract(reference)
            if extracted is not None:
                day = self._dates.resolve(extracted, today=today)
                if day is not None:
                    return day, day
        return today.replace(day=1), today
