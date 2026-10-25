"""Conversation dispatch across banking and finance use cases."""

from __future__ import annotations

from myfinance.application.dto import (
    ChatReply,
    HandleMessageResult,
    HelpMessage,
    IncomeMessage,
    NeedsClarification,
    PeriodDetails,
    RegisteredMessage,
    SummaryMessage,
)
from myfinance.application.intents import MessageIntent, RoutingDecision
from myfinance.application.ports import (
    Clock,
    DateReferenceExtractor,
    MessageIntentRouter,
    MessageParser,
)
from myfinance.application.use_cases.banking import HandleBankingQueryUseCase
from myfinance.application.use_cases.common import run_with_timeout
from myfinance.application.use_cases.entries import (
    GetDailySummaryUseCase,
    GetPeriodDetailsUseCase,
    GetPeriodSummaryUseCase,
    RegisterEntryUseCase,
)
from myfinance.application.use_cases.insights import (
    GetTopSpendingMonthUseCase,
)
from myfinance.application.use_cases.plans import GetSpendingPlanUseCase
from myfinance.application.use_cases.spending import SearchSpendingUseCase

__all__ = ["HandleConversationMessageUseCase", "HandleMessageUseCase"]

_SPENDING_SEARCH_TIMEOUT_SECONDS = 45
_SPENDING_PLAN_TIMEOUT_SECONDS = 60
_TOP_MONTH_TIMEOUT_SECONDS = 45


class HandleMessageUseCase:
    """Dispatch a finance message to the use case for its intent."""

    def __init__(
        self,
        router: MessageIntentRouter,
        parser: MessageParser,
        register: RegisterEntryUseCase,
        clock: Clock,
        summary: GetDailySummaryUseCase,
        references: DateReferenceExtractor,
        period_summary: GetPeriodSummaryUseCase | None = None,
        top_month: GetTopSpendingMonthUseCase | None = None,
        spending_search: SearchSpendingUseCase | None = None,
        spending_plan: GetSpendingPlanUseCase | None = None,
        period_details: GetPeriodDetailsUseCase | None = None,
        *,
        search_timeout: float = _SPENDING_SEARCH_TIMEOUT_SECONDS,
        plan_timeout: float = _SPENDING_PLAN_TIMEOUT_SECONDS,
        top_month_timeout: float = _TOP_MONTH_TIMEOUT_SECONDS,
    ) -> None:
        self._router = router
        self._parser = parser
        self._register = register
        self._clock = clock
        self._summary = summary
        self._references = references
        self._period_summary = period_summary
        self._top_month = top_month
        self._spending_search = spending_search
        self._spending_plan = spending_plan
        self._period_details = period_details
        self._search_timeout = search_timeout
        self._plan_timeout = plan_timeout
        self._top_month_timeout = top_month_timeout

    async def execute(
        self, text: str, decision: RoutingDecision | None = None
    ) -> HandleMessageResult:
        decision = decision or await self._router.route(text)
        intent = decision.intent

        if intent is MessageIntent.HELP:
            return HelpMessage()

        if intent is MessageIntent.INCOME:
            return IncomeMessage()

        if intent is MessageIntent.PERIOD_DETAILS and self._period_details:
            return await self._period_details.execute(text)

        if intent is MessageIntent.SPENDING_SEARCH and self._spending_search:
            answer = await run_with_timeout(
                self._spending_search.execute(text),
                self._search_timeout,
                "A consulta de gastos demorou demais. Tente novamente.",
            )
            if answer is not None:
                return answer

        if intent is MessageIntent.SPENDING_PLAN and self._spending_plan:
            return await run_with_timeout(
                self._spending_plan.execute(text),
                self._plan_timeout,
                "O plano de gastos demorou demais. Tente novamente.",
            )

        if intent is MessageIntent.TOP_MONTH and self._top_month:
            return await run_with_timeout(
                self._top_month.execute(),
                self._top_month_timeout,
                "A consulta de meses demorou demais. Tente novamente.",
            )

        if intent in {
            MessageIntent.SPENDING_SEARCH,
            MessageIntent.SPENDING_PLAN,
            MessageIntent.TOP_MONTH,
            MessageIntent.SUMMARY,
            MessageIntent.PERIOD_DETAILS,
        }:
            return await self._summary_result(text)

        return await self._register_result(text)

    async def _summary_result(self, text: str) -> SummaryMessage:
        if self._period_summary is not None:
            period = await self._period_summary.execute(text)
            if period is not None:
                return SummaryMessage(summary=period)
        reference = self._references.extract(text)
        summary = await self._summary.execute(reference)
        return SummaryMessage(summary=summary)

    async def _register_result(self, text: str) -> HandleMessageResult:
        parsed = await self._parser.parse(text, today=self._clock.today())
        if parsed is None:
            return NeedsClarification(
                "Não consegui identificar valor e data. "
                "Tente algo como: almoço hoje 45."
            )
        return RegisteredMessage(
            parsed=parsed, result=await self._register.execute(parsed)
        )


class HandleConversationMessageUseCase:
    """Route a message once and dispatch it to banking or finance."""

    def __init__(
        self,
        router: MessageIntentRouter,
        banking: HandleBankingQueryUseCase,
        messages: HandleMessageUseCase,
    ) -> None:
        self._router = router
        self._banking = banking
        self._messages = messages

    async def execute(self, text: str) -> ChatReply:
        decision = await self._router.route(text)
        if decision.intent is MessageIntent.BANKING:
            answer = await self._banking.execute(
                text, intent=decision.banking_intent
            )
            if answer is not None:
                return answer
        return await self._messages.execute(text, decision)
