"""Unit tests for the natural-language message routing use case."""

from __future__ import annotations

from datetime import UTC, date, datetime

from myfinance.application.dto import (
    NeedsClarification,
    RegisteredMessage,
    SummaryMessage,
)
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
)
from myfinance.domain.entries import Entry
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.infrastructure.routing.messages import (
    DeterministicMessageIntentRouter,
)

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now


class InMemoryEntryRepository:
    def __init__(self) -> None:
        self.entries: list[Entry] = []

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)


def build_use_case(
    repository: InMemoryEntryRepository,
    summary_gate: FakeSummaryGate | None = None,
) -> HandleMessageUseCase:
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    return HandleMessageUseCase(
        DeterministicMessageIntentRouter(summary_gate),
        DeterministicMessageParser(resolver),
        RegisterEntryUseCase(repository, clock),
        clock,
        GetDailySummaryUseCase(repository, clock, resolver),
        PortugueseDateReferenceExtractor(),
    )


async def test_summary_intent_for_today_returns_a_summary_message() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("Como estão meus gastos de hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY


async def test_summary_intent_resolves_a_weekday() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("Quanto planejei para sábado?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == date(2026, 10, 24)


async def test_summary_intent_resolves_yesterday() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("Quanto gastei ontem?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == date(2026, 10, 19)


async def test_summary_intent_accepts_a_filler_word() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("quanto ja gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY


async def test_bare_expense_without_quanto_is_registered() -> None:
    repository = InMemoryEntryRepository()
    use_case = build_use_case(repository)

    result = await use_case.execute("gastei 45")

    assert isinstance(result, RegisteredMessage)
    assert result.parsed.amount.cents == 4500
    assert len(repository.entries) == 1


async def test_registration_still_wins_when_the_message_has_an_amount() -> None:
    repository = InMemoryEntryRepository()
    use_case = build_use_case(repository)

    result = await use_case.execute("Almoço hoje 45")

    assert isinstance(result, RegisteredMessage)
    assert result.parsed.amount.cents == 4500
    assert result.parsed.day == TODAY
    assert len(repository.entries) == 1


async def test_unparseable_text_needs_clarification() -> None:
    use_case = build_use_case(InMemoryEntryRepository())

    result = await use_case.execute("oi tudo bem")

    assert isinstance(result, NeedsClarification)
    assert "valor e data" in result.reason


async def test_summary_totals_reflect_registered_entries() -> None:
    repository = InMemoryEntryRepository()
    use_case = build_use_case(repository)
    await use_case.execute("Almoço hoje deu 45")
    await use_case.execute("Previsão de 80 no mercado hoje")

    result = await use_case.execute("Como estão meus gastos de hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.total_forecast_cents == 8000
    assert result.summary.total_expense_cents == 4500
    assert result.summary.total_difference_cents == 3500
    assert result.summary.has_deficit is False


class FakeSummaryGate:
    """A SummaryIntentGate that records calls and returns or raises a decision."""

    def __init__(
        self,
        decision: bool | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision
        self.error = error
        self.calls: list[str] = []

    async def should_summarize(self, text: str) -> bool | None:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.decision


async def test_gate_decision_wins_over_the_regex() -> None:
    gate = FakeSummaryGate(False)
    use_case = build_use_case(InMemoryEntryRepository(), gate)

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, NeedsClarification)
    assert gate.calls == ["quanto gastei hoje?"]


async def test_gate_none_uses_the_regex_fallback() -> None:
    use_case = build_use_case(InMemoryEntryRepository(), FakeSummaryGate(None))

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY


async def test_gate_provider_error_uses_the_regex_fallback() -> None:
    gate = FakeSummaryGate(error=ProviderError("provider down"))
    use_case = build_use_case(InMemoryEntryRepository(), gate)

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY
