"""Unit tests for the unified message intent router."""

from __future__ import annotations

import pytest

from myfinance.application.dto import NeedsClarification, NoPluggyItem
from myfinance.application.intents import MessageIntent
from myfinance.application.use_cases import HandleConversationMessageUseCase
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.routing.messages import (
    CompositeMessageIntentRouter,
    DeterministicMessageIntentRouter,
)


class FakeSummaryGate:
    def __init__(self, decision: bool | None = None) -> None:
        self._decision = decision

    async def should_summarize(self, text: str) -> bool | None:
        return self._decision


class FakeJevRouter:
    def __init__(self, intent: BankingIntent) -> None:
        self._intent = intent

    async def route(self, text: str) -> BankingIntent:
        return self._intent


def build_router(
    *,
    gate: FakeSummaryGate | None = None,
    jev: FakeJevRouter | None = None,
) -> CompositeMessageIntentRouter:
    return CompositeMessageIntentRouter(jev=jev, summary_gate=gate)


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("qual meu saldo", MessageIntent.BANKING),
        ("extrato de hoje", MessageIntent.BANKING),
        ("meus dados do cartão", MessageIntent.BANKING),
        ("quanto gastei com uber esse mês?", MessageIntent.SPENDING_SEARCH),
        ("onde posso cortar gastos?", MessageIntent.SPENDING_PLAN),
        ("quanto gastei hoje?", MessageIntent.SUMMARY),
        ("gastei 45", MessageIntent.REGISTER),
        ("Almoço hoje 45", MessageIntent.REGISTER),
    ],
)
async def test_router_classifies_the_main_intents(
    text: str, intent: MessageIntent
) -> None:
    decision = await build_router().route(text)

    assert decision.intent is intent


async def test_strong_banking_phrase_carries_the_subtype() -> None:
    decision = await build_router().route("qual meu saldo")

    assert decision.intent is MessageIntent.BANKING
    assert decision.banking_intent is BankingIntent.ACCOUNTS


@pytest.mark.parametrize(
    "text",
    [
        "quanto eu tenho na conta?",
        "quanto tem na minha conta",
        "quanto a gente tem na conta",
        "quanto temos na conta",
        "tenho quanto na conta",
        "quanto eu tenho de saldo",
        "quanto eu tenho disponível",
        "quanto eu tenho em caixa",
        "quanto eu tenho?",
    ],
)
async def test_account_questions_with_pronouns_route_to_accounts(
    text: str,
) -> None:
    decision = await build_router().route(text)

    assert decision.intent is MessageIntent.BANKING
    assert decision.banking_intent is BankingIntent.ACCOUNTS


@pytest.mark.parametrize(
    "text",
    [
        "Quanto eu recebi esse mês?",
        "quanto ganhei esse mês",
        "quanto entrou na conta",
        "meu salário",
        "recebi 100",
    ],
)
async def test_income_questions_route_to_income(text: str) -> None:
    decision = await build_router().route(text)

    assert decision.intent is MessageIntent.INCOME


async def test_period_details_question_routes_to_details() -> None:
    decision = await build_router().route(
        "quero os lançamentos do mês de set/2026"
    )

    assert decision.intent is MessageIntent.PERIOD_DETAILS


@pytest.mark.parametrize(
    "text",
    [
        "meus gastos com uber",
        "gastos de uber",
        "gastos com alimentação",
        "gastei com uber",
    ],
)
async def test_gasto_phrases_with_a_subject_reach_the_search(text: str) -> None:
    decision = await build_router().route(text)

    assert decision.intent is MessageIntent.SPENDING_SEARCH


@pytest.mark.parametrize(
    "text",
    [
        "Como estão meus gastos de hoje?",
        "Quero meus gastos do mês por categoria",
        "quanto deu hoje?",
        "quanto ficou?",
        "quanto custou?",
    ],
)
async def test_period_summary_phrases_stay_summaries(text: str) -> None:
    decision = await build_router().route(text)

    assert decision.intent is MessageIntent.SUMMARY


@pytest.mark.parametrize(
    "text",
    [
        "O que você pode fazer?",
        "o que voce faz",
        "o que você sabe",
        "para que você serve?",
        "como você funciona?",
        "quais são suas funções?",
        "quais comandos",
        "me ajuda",
        "pode me ajudar?",
        "ajuda",
    ],
)
async def test_capability_questions_route_to_help(text: str) -> None:
    decision = await build_router().route(text)

    assert decision.intent is MessageIntent.HELP


async def test_savings_help_still_routes_to_the_spending_plan() -> None:
    decision = await build_router().route("me ajuda a economizar")

    assert decision.intent is MessageIntent.SPENDING_PLAN


async def test_forecast_question_is_not_an_account_question() -> None:
    decision = await build_router().route("quanto tenho de gastos esse mês?")

    assert decision.intent is MessageIntent.SUMMARY


async def test_top_month_is_detected_without_the_gate() -> None:
    decision = await build_router().route(
        "qual foi o mês que eu mais gastei?"
    )

    assert decision.intent is MessageIntent.TOP_MONTH


async def test_spending_question_with_card_word_beats_the_ambiguous_hint() -> None:
    decision = await build_router(
        jev=FakeJevRouter(BankingIntent.TRANSACTIONS)
    ).route("quanto gastei com uber no cartão?")

    assert decision.intent is MessageIntent.SPENDING_SEARCH


async def test_ambiguous_banking_hint_is_checked_after_finance() -> None:
    decision = await build_router(
        jev=FakeJevRouter(BankingIntent.IDENTITY)
    ).route("meu cartão sumiu")

    assert decision.intent is MessageIntent.BANKING
    assert decision.banking_intent is BankingIntent.IDENTITY


async def test_ambiguous_banking_hint_without_jev_falls_back_to_register() -> None:
    decision = await build_router().route("meu cartão sumiu")

    assert decision.intent is MessageIntent.REGISTER


async def test_summary_gate_true_routes_top_month() -> None:
    decision = await build_router(gate=FakeSummaryGate(True)).route(
        "qual foi o mês que eu mais gastei?"
    )

    assert decision.intent is MessageIntent.TOP_MONTH


async def test_summary_gate_false_overrides_the_regex() -> None:
    decision = await build_router(gate=FakeSummaryGate(False)).route(
        "quanto gastei hoje?"
    )

    assert decision.intent is MessageIntent.REGISTER


async def test_deterministic_router_ignores_banking() -> None:
    decision = await DeterministicMessageIntentRouter().route(
        "qual meu saldo"
    )

    assert decision.intent is MessageIntent.REGISTER


class FakeBanking:
    def __init__(self, answer: object) -> None:
        self._answer = answer
        self.calls: list[tuple[str, BankingIntent | None]] = []

    async def execute(
        self, text: str, *, intent: BankingIntent | None = None
    ) -> object:
        self.calls.append((text, intent))
        return self._answer


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def execute(self, text: str, decision=None) -> object:
        self.calls.append((text, decision))
        return NeedsClarification("messages")


async def test_conversation_dispatches_account_question_to_banking() -> None:
    banking = FakeBanking(NoPluggyItem())
    messages = FakeMessages()
    use_case = HandleConversationMessageUseCase(
        build_router(),
        banking,  # type: ignore[arg-type]
        messages,  # type: ignore[arg-type]
    )

    result = await use_case.execute("quanto eu tenho na conta?")

    assert isinstance(result, NoPluggyItem)
    assert banking.calls == [
        ("quanto eu tenho na conta?", BankingIntent.ACCOUNTS)
    ]
    assert messages.calls == []


async def test_conversation_dispatches_gasto_phrase_to_finance() -> None:
    banking = FakeBanking(NoPluggyItem())
    messages = FakeMessages()
    use_case = HandleConversationMessageUseCase(
        build_router(),
        banking,  # type: ignore[arg-type]
        messages,  # type: ignore[arg-type]
    )

    await use_case.execute("meus gastos com uber")

    assert banking.calls == []
    assert messages.calls[0][0] == "meus gastos com uber"
    assert messages.calls[0][1].intent is MessageIntent.SPENDING_SEARCH
