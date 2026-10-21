"""Unit tests for period summaries (month, week, rolling windows)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from myfinance.application.dto import (
    NeedsClarification,
    RegisteredMessage,
    SummaryMessage,
)
from myfinance.application.periods import resolve_period
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodSummaryUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
)
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import DailySummary, PeriodSummary, build_period_summary
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.infrastructure.sqlite import SqliteDatabase, SqliteEntryRepository
from myfinance.presentation.telegram.handlers import BotHandlers

TODAY = date(2026, 10, 20)
YESTERDAY = date(2026, 10, 19)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now


class InMemoryEntryRepository:
    def __init__(self, entries: list[Entry] | None = None) -> None:
        self.entries: list[Entry] = list(entries or [])

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class InMemoryProcessedUpdates:
    def __init__(self) -> None:
        self.seen: set[int] = set()

    async def claim(self, update_id: int) -> bool:
        if update_id in self.seen:
            return False
        self.seen.add(update_id)
        return True


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


def make_entry(
    day: date,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
    amount_cents: int = 4500,
    category: Category = Category.ALIMENTACAO,
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(amount_cents),
        description="lançamento",
        category=category,
        created_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    )


def build_use_case(repository: InMemoryEntryRepository) -> HandleMessageUseCase:
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    return HandleMessageUseCase(
        DeterministicMessageParser(resolver),
        RegisterEntryUseCase(repository, clock),
        clock,
        GetDailySummaryUseCase(repository, clock, resolver),
        PortugueseDateReferenceExtractor(),
        GetPeriodSummaryUseCase(repository, clock),
    )


def build_handlers(repository: InMemoryEntryRepository) -> BotHandlers:
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    summary = GetDailySummaryUseCase(repository, clock, resolver)
    period = GetPeriodSummaryUseCase(repository, clock)
    return BotHandlers(
        handle_message=HandleMessageUseCase(
            DeterministicMessageParser(resolver),
            RegisterEntryUseCase(repository, clock),
            clock,
            summary,
            PortugueseDateReferenceExtractor(),
            period,
        ),
        summary=summary,
        details=GetDayDetailsUseCase(repository, clock, resolver),
        updates=InMemoryProcessedUpdates(),
        period_summary=period,
    )


def test_resolve_period_understands_the_current_month() -> None:
    assert resolve_period("quanto gastei esse mes", today=TODAY) == (
        date(2026, 10, 1),
        date(2026, 10, 20),
    )


def test_resolve_period_understands_the_previous_month() -> None:
    assert resolve_period("mes passado", today=TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )


def test_resolve_period_understands_the_current_week() -> None:
    assert resolve_period("essa semana", today=TODAY) == (
        date(2026, 10, 19),
        date(2026, 10, 20),
    )


def test_resolve_period_understands_the_last_seven_days() -> None:
    assert resolve_period("ultimos 7 dias", today=TODAY) == (
        date(2026, 10, 14),
        date(2026, 10, 20),
    )


def test_resolve_period_understands_the_previous_week() -> None:
    assert resolve_period("semana passada", today=TODAY) == (
        date(2026, 10, 12),
        date(2026, 10, 18),
    )


def test_resolve_period_understands_nessa_semana() -> None:
    assert resolve_period("nessa semana", today=TODAY) == (
        date(2026, 10, 19),
        date(2026, 10, 20),
    )


def test_resolve_period_understands_neste_mes() -> None:
    assert resolve_period("neste mes", today=TODAY) == (
        date(2026, 10, 1),
        date(2026, 10, 20),
    )


def test_resolve_period_ignores_day_references() -> None:
    assert resolve_period("hoje", today=TODAY) is None
    assert resolve_period("resumo", today=TODAY) is None
    assert resolve_period(None, today=TODAY) is None


def test_resolve_period_understands_do_mes_in_a_natural_phrase() -> None:
    assert resolve_period(
        "Quero meus gastos do mês por categoria", today=TODAY
    ) == (
        date(2026, 10, 1),
        date(2026, 10, 20),
    )


def test_resolve_period_understands_no_mes() -> None:
    assert resolve_period("gastos no mes", today=TODAY) == (
        date(2026, 10, 1),
        date(2026, 10, 20),
    )


def test_resolve_period_do_mes_passado_wins_over_do_mes() -> None:
    assert resolve_period("gastos do mes passado", today=TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )


def test_resolve_period_do_mes_que_vem_resolves_to_next_month() -> None:
    assert resolve_period("gastos do mes que vem", today=TODAY) == (
        date(2026, 11, 1),
        date(2026, 11, 30),
    )


def test_build_period_summary_aggregates_entries_across_days() -> None:
    entries = (
        make_entry(
            date(2026, 10, 1),
            kind=EntryKind.FORECAST,
            amount_cents=10000,
            category=Category.ALIMENTACAO,
        ),
        make_entry(date(2026, 10, 15), amount_cents=4500),
        make_entry(
            date(2026, 10, 20),
            amount_cents=8000,
            category=Category.TRANSPORTE,
        ),
    )

    summary = build_period_summary(date(2026, 10, 1), TODAY, entries)

    assert summary.start == date(2026, 10, 1)
    assert summary.end == TODAY
    assert summary.total_forecast_cents == 10000
    assert summary.total_expense_cents == 12500
    assert summary.total_difference_cents == -2500
    assert summary.has_deficit is True


async def test_message_current_month_aggregates_only_october() -> None:
    repository = InMemoryEntryRepository(
        [
            make_entry(date(2026, 10, 1), amount_cents=4500),
            make_entry(date(2026, 10, 15), amount_cents=2000),
            make_entry(date(2026, 9, 30), amount_cents=9999),
        ]
    )
    use_case = build_use_case(repository)

    result = await use_case.execute("quanto gastei esse mes?")

    assert isinstance(result, SummaryMessage)
    assert isinstance(result.summary, PeriodSummary)
    assert result.summary.start == date(2026, 10, 1)
    assert result.summary.end == TODAY
    assert result.summary.total_expense_cents == 6500


async def test_message_with_filler_word_still_returns_the_month_summary() -> None:
    repository = InMemoryEntryRepository(
        [make_entry(date(2026, 10, 1), amount_cents=4500)]
    )
    use_case = build_use_case(repository)

    result = await use_case.execute("quanto ja gastei esse mes?")

    assert isinstance(result, SummaryMessage)
    assert isinstance(result.summary, PeriodSummary)
    assert result.summary.start == date(2026, 10, 1)
    assert result.summary.end == TODAY


async def test_message_last_week_covers_the_previous_calendar_week() -> None:
    repository = InMemoryEntryRepository(
        [
            make_entry(date(2026, 10, 12), amount_cents=1000),
            make_entry(date(2026, 10, 18), amount_cents=2500),
            make_entry(date(2026, 10, 19), amount_cents=9999),
        ]
    )
    use_case = build_use_case(repository)

    result = await use_case.execute("Quanto gastei semana passada?")

    assert isinstance(result, SummaryMessage)
    assert isinstance(result.summary, PeriodSummary)
    assert result.summary.start == date(2026, 10, 12)
    assert result.summary.end == date(2026, 10, 18)
    assert result.summary.total_expense_cents == 3500


async def test_message_greeting_needs_clarification() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("oi")

    assert isinstance(result, NeedsClarification)
    assert "valor e data" in result.reason


async def test_message_bare_expense_is_still_registered() -> None:
    repository = InMemoryEntryRepository()
    use_case = build_use_case(repository)

    result = await use_case.execute("gastei 45")

    assert isinstance(result, RegisteredMessage)
    assert result.parsed.amount.cents == 4500
    assert len(repository.entries) == 1


async def test_message_yesterday_still_returns_a_daily_summary() -> None:
    repository = InMemoryEntryRepository([make_entry(YESTERDAY)])
    use_case = build_use_case(repository)

    result = await use_case.execute("quanto gastei ontem?")

    assert isinstance(result, SummaryMessage)
    assert isinstance(result.summary, DailySummary)
    assert result.summary.day == YESTERDAY


async def test_sqlite_list_between_includes_only_the_range(
    tmp_path: Path,
) -> None:
    repository = SqliteEntryRepository(SqliteDatabase(tmp_path / "test.db"))
    inside_first = make_entry(date(2026, 10, 1))
    inside_last = make_entry(TODAY)
    before = make_entry(date(2026, 9, 30))
    after = make_entry(date(2026, 10, 21))
    for entry in (inside_first, inside_last, before, after):
        await repository.add(entry)

    entries = await repository.list_between(date(2026, 10, 1), TODAY)

    assert [entry.id for entry in entries] == [inside_first.id, inside_last.id]


async def test_summary_command_renders_a_month_period() -> None:
    repository = InMemoryEntryRepository([make_entry(date(2026, 10, 1))])
    handlers = build_handlers(repository)
    message = FakeMessage()
    update = SimpleNamespace(update_id=1, effective_message=message)

    await handlers.summary(update, SimpleNamespace(args=["esse", "mes"]))

    assert message.replies[0].startswith("Resumo de 01/10/2026 a")
