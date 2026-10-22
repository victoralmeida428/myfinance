"""Unit tests for strict spending-query routing in HandleMessageUseCase."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from myfinance.application import use_cases as use_cases_module
from myfinance.application.dto import (
    RegisteredMessage,
    SpendingAnswerMessage,
    SummaryMessage,
    TopMonthMessage,
)
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    GetPeriodSummaryUseCase,
    GetTopSpendingMonthUseCase,
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

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

ANSWER = SpendingAnswerMessage(
    start=date(2026, 10, 1),
    end=TODAY,
    label="Uber",
    total_cents=2500,
    count=1,
    category=None,
    keywords=("uber",),
)


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

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class FakeBankExpenses:
    async def expenses(
        self, start: date, end: date
    ) -> tuple[object, ...]:
        return ()


class FakeSummaryGate:
    def __init__(self, decision: bool) -> None:
        self._decision = decision

    async def should_summarize(self, text: str) -> bool:
        return self._decision


class FakeSpendingSearch:
    def __init__(
        self,
        answer: SpendingAnswerMessage | None,
        *,
        delay: float = 0.0,
    ) -> None:
        self._answer = answer
        self._delay = delay
        self.calls: list[str] = []

    async def execute(self, text: str) -> SpendingAnswerMessage | None:
        self.calls.append(text)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._answer


def build_use_case(
    search: FakeSpendingSearch | None = None,
    repository: InMemoryEntryRepository | None = None,
    summary_gate: FakeSummaryGate | None = None,
) -> tuple[HandleMessageUseCase, InMemoryEntryRepository]:
    repository = repository or InMemoryEntryRepository()
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    use_case = HandleMessageUseCase(
        DeterministicMessageParser(resolver),
        RegisterEntryUseCase(repository, clock),
        clock,
        GetDailySummaryUseCase(repository, clock, resolver),
        PortugueseDateReferenceExtractor(),
        GetPeriodSummaryUseCase(repository, clock),
        summary_gate,
        GetTopSpendingMonthUseCase(repository, FakeBankExpenses(), clock),
        search,
    )
    return use_case, repository


async def test_subject_query_with_month_is_answered_by_the_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei com uber esse mês?")

    assert isinstance(result, SpendingAnswerMessage)
    assert search.calls == ["quanto gastei com uber esse mês?"]


async def test_category_subject_query_is_answered_by_the_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei com alimentos?")

    assert isinstance(result, SpendingAnswerMessage)
    assert search.calls == ["quanto gastei com alimentos?"]


async def test_place_subject_query_is_answered_by_the_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto em posto de gasolina?")

    assert isinstance(result, SpendingAnswerMessage)
    assert search.calls == ["quanto em posto de gasolina?"]


async def test_period_only_today_question_keeps_the_daily_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY
    assert search.calls == []


async def test_period_only_month_question_keeps_the_month_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei esse mês?")

    assert isinstance(result, SummaryMessage)
    assert search.calls == []


async def test_pronoun_only_today_question_keeps_the_daily_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto eu gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY
    assert search.calls == []


async def test_banking_account_question_keeps_the_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei na conta?")

    assert isinstance(result, SummaryMessage)
    assert search.calls == []


async def test_card_question_keeps_the_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei no cartão?")

    assert isinstance(result, SummaryMessage)
    assert search.calls == []


async def test_purchases_question_keeps_the_summary() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei com compras?")

    assert isinstance(result, SummaryMessage)
    assert search.calls == []


async def test_merchant_subject_with_card_word_still_reaches_the_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    text = "quanto gastei com uber no cartão?"
    result = await use_case.execute(text)

    assert isinstance(result, SpendingAnswerMessage)
    assert search.calls == [text]


async def test_bare_expense_without_quanto_is_registered() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, repository = build_use_case(search)

    result = await use_case.execute("gastei 45")

    assert isinstance(result, RegisteredMessage)
    assert result.parsed.amount.cents == 4500
    assert len(repository.entries) == 1
    assert search.calls == []


async def test_expense_with_subject_but_without_quanto_is_registered() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, repository = build_use_case(search)

    result = await use_case.execute("Almoço hoje 45")

    assert isinstance(result, RegisteredMessage)
    assert result.parsed.amount.cents == 4500
    assert len(repository.entries) == 1
    assert search.calls == []


async def test_top_month_question_skips_the_spending_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search, summary_gate=FakeSummaryGate(True))

    result = await use_case.execute("Qual foi o mês que eu mais gastei?")

    assert isinstance(result, TopMonthMessage)
    assert search.calls == []


async def test_search_returning_none_falls_back_to_the_summary_flow() -> None:
    search = FakeSpendingSearch(None)
    use_case, _ = build_use_case(search)

    result = await use_case.execute("quanto gastei com uber?")

    assert isinstance(result, SummaryMessage)
    assert search.calls == ["quanto gastei com uber?"]


async def test_search_timeout_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        use_cases_module, "_SPENDING_SEARCH_TIMEOUT_SECONDS", 0.01
    )
    search = FakeSpendingSearch(ANSWER, delay=1.0)
    use_case, _ = build_use_case(search)

    with pytest.raises(ProviderError, match="demorou demais"):
        await use_case.execute("quanto gastei com uber?")

    assert search.calls == ["quanto gastei com uber?"]


@pytest.mark.parametrize(
    ("text", "search_expected"),
    [
        ("quanto gastei?", False),
        ("quanto gastei esse mês?", False),
        ("quanto gastei em 12/10?", False),
        ("quanto gastei em 2025?", False),
        ("gastei 45", False),
        ("Almoço hoje 45", False),
        ("quanto gastei com uber em 2025?", True),
        ("quanto gastei de almoço em outubro?", True),
        ("quanto eu gastei hoje?", False),
        ("quanto deu hoje?", False),
        ("quanto ficou?", False),
        ("quanto a gente gastou?", False),
        ("quanto custou?", False),
        ("quanto custa uber?", True),
        ("quanto custa?", False),
        ("quanto gastei no mercado central 50", False),
        ("quanto gastei com uber 45", False),
        ("quanto gastei com uber em 12/10?", True),
        ("quanto gastei na conta?", False),
        ("quanto gastei no cartão?", False),
        ("quanto gastei com compras?", False),
        ("quanto gastei na conta em outubro?", False),
        ("quanto gastei de fatura?", False),
        ("quanto gastei no pix?", False),
        ("quanto gastei com uber e compras?", True),
        ("quanto gastei com uber no cartão?", True),
    ],
)
async def test_detector_edge_classes(
    text: str, search_expected: bool
) -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    await use_case.execute(text)

    assert bool(search.calls) is search_expected
