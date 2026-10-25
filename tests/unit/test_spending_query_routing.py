"""Unit tests for strict spending-query routing in HandleMessageUseCase."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from myfinance.application.dto import (
    HelpMessage,
    IncomeMessage,
    PeriodDetails,
    RegisteredMessage,
    SpendingAnswerMessage,
    SpendingPlanMessage,
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
from myfinance.infrastructure.routing.messages import (
    DeterministicMessageIntentRouter,
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

PLAN = SpendingPlanMessage(
    start=date(2026, 9, 1),
    end=date(2026, 9, 30),
    total_cents=49000,
    count=7,
    previous_total_cents=32000,
    categories=(),
    merchants=(),
    target_cents=4900,
    cuts=(),
    narrative=None,
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


class FakeSpendingPlan:
    def __init__(
        self,
        plan: SpendingPlanMessage = PLAN,
        *,
        delay: float = 0.0,
    ) -> None:
        self._plan = plan
        self._delay = delay
        self.calls: list[str] = []

    async def execute(self, text: str = "") -> SpendingPlanMessage:
        self.calls.append(text)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._plan


class FakePeriodDetails:
    def __init__(self, details: PeriodDetails) -> None:
        self._details = details
        self.calls: list[str] = []

    async def execute(self, text: str = "") -> PeriodDetails:
        self.calls.append(text)
        return self._details


def build_use_case(
    search: FakeSpendingSearch | None = None,
    repository: InMemoryEntryRepository | None = None,
    summary_gate: FakeSummaryGate | None = None,
    plan: FakeSpendingPlan | None = None,
    *,
    search_timeout: float = 45.0,
    plan_timeout: float = 60.0,
    period_details: FakePeriodDetails | None = None,
) -> tuple[HandleMessageUseCase, InMemoryEntryRepository]:
    repository = repository or InMemoryEntryRepository()
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    use_case = HandleMessageUseCase(
        DeterministicMessageIntentRouter(summary_gate),
        DeterministicMessageParser(resolver),
        RegisterEntryUseCase(repository, clock),
        clock,
        GetDailySummaryUseCase(repository, clock, resolver),
        PortugueseDateReferenceExtractor(),
        GetPeriodSummaryUseCase(repository, clock),
        GetTopSpendingMonthUseCase(repository, FakeBankExpenses(), clock),
        search,
        plan,
        period_details,
        search_timeout=search_timeout,
        plan_timeout=plan_timeout,
    )
    return use_case, repository


async def test_capability_question_returns_the_help_message() -> None:
    use_case, _ = build_use_case()

    result = await use_case.execute("O que você pode fazer?")

    assert isinstance(result, HelpMessage)


async def test_income_question_returns_the_income_message() -> None:
    use_case, _ = build_use_case()

    result = await use_case.execute("Quanto eu recebi esse mês?")

    assert isinstance(result, IncomeMessage)


async def test_period_details_question_is_dispatched() -> None:
    details = PeriodDetails(
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        items=(),
    )
    fake = FakePeriodDetails(details)
    use_case, _ = build_use_case(period_details=fake)
    question = "quero os lançamentos do mês de set/2026"

    result = await use_case.execute(question)

    assert result is details
    assert fake.calls == [question]


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


async def test_search_timeout_raises_provider_error() -> None:
    search = FakeSpendingSearch(ANSWER, delay=1.0)
    use_case, _ = build_use_case(search, search_timeout=0.01)

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


async def test_year_period_subject_query_is_answered_by_the_search() -> None:
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search)

    text = "quanto gastei de gasolina esse ano?"
    result = await use_case.execute(text)

    assert isinstance(result, SpendingAnswerMessage)
    assert search.calls == [text]


async def test_savings_question_is_answered_by_the_spending_plan() -> None:
    plan = FakeSpendingPlan()
    use_case, _ = build_use_case(plan=plan)

    result = await use_case.execute("onde posso cortar gastos?")

    assert result == PLAN
    assert plan.calls == ["onde posso cortar gastos?"]


async def test_how_to_save_question_is_answered_by_the_spending_plan() -> None:
    plan = FakeSpendingPlan()
    use_case, _ = build_use_case(plan=plan)

    result = await use_case.execute("como economizar mais?")

    assert result == PLAN
    assert plan.calls == ["como economizar mais?"]


async def test_plan_request_is_answered_by_the_spending_plan() -> None:
    plan = FakeSpendingPlan()
    use_case, _ = build_use_case(plan=plan)

    result = await use_case.execute("faça um plano de gastos")

    assert result == PLAN
    assert plan.calls == ["faça um plano de gastos"]


async def test_period_summary_question_is_not_a_spending_plan() -> None:
    plan = FakeSpendingPlan()
    search = FakeSpendingSearch(ANSWER)
    use_case, _ = build_use_case(search, plan=plan)

    result = await use_case.execute("quanto gastei no mês passado?")

    assert isinstance(result, SummaryMessage)
    assert plan.calls == []


async def test_bare_expense_never_reaches_the_spending_plan() -> None:
    plan = FakeSpendingPlan()
    use_case, repository = build_use_case(plan=plan)

    result = await use_case.execute("gastei 45")

    assert isinstance(result, RegisteredMessage)
    assert plan.calls == []
    assert len(repository.entries) == 1


async def test_plan_timeout_raises_provider_error() -> None:
    plan = FakeSpendingPlan(delay=1.0)
    use_case, _ = build_use_case(plan=plan, plan_timeout=0.01)

    with pytest.raises(ProviderError, match="plano de gastos demorou demais"):
        await use_case.execute("onde posso cortar gastos?")
