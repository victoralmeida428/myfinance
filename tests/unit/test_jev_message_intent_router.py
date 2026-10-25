"""Unit tests for the JEV-backed message intent classifier."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from myfinance.application.intents import MessageIntent, RoutingDecision
from myfinance.config import Settings
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.routing.keywords import KeywordIntentRouter
from myfinance.infrastructure.routing.messages import (
    CompositeMessageIntentRouter,
)
from myfinance.infrastructure.routing.jev_messages import (
    JevMessageIntentRouter,
)

BASE_URL = "https://api.typesafe.ai"


def _settings(*, token: str | None = "test") -> Settings:
    return Settings(
        _env_file=None,
        categorizer_api_token=token,
        categorizer_model="jev-latest",
        categorizer_base_url=BASE_URL,
    )


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _response(*, choice: str | None = None) -> dict[str, object]:
    answer: dict[str, object] = {"type": "choice", "confidence": 1.0}
    if choice is not None:
        answer["choice"] = choice
    return {
        "model": "jev-1.13.0",
        "answers": {"intent": answer},
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def test_classifier_sends_the_expected_systemone_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response(choice="summary"))

    router = JevMessageIntentRouter(
        _settings(), http_client=_client(handler)
    )

    decision = await router.classify("resumo da semana")

    assert decision is not None
    assert decision.intent is MessageIntent.SUMMARY
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    headers = captured["headers"]
    assert headers["authorization"] == "Bearer test"

    body = captured["body"]
    assert body["model"] == "jev-latest"
    assert body["state"] == "resumo da semana"
    criteria = body["questions"]["intent"]["criteria"]
    assert "spending_search" in criteria
    assert "period_details" in criteria
    assert "help" in criteria
    assert "income" in criteria


@pytest.mark.parametrize(
    ("choice", "intent", "banking_intent"),
    [
        ("banking_accounts", MessageIntent.BANKING, BankingIntent.ACCOUNTS),
        (
            "banking_transactions",
            MessageIntent.BANKING,
            BankingIntent.TRANSACTIONS,
        ),
        ("banking_identity", MessageIntent.BANKING, BankingIntent.IDENTITY),
        ("spending_search", MessageIntent.SPENDING_SEARCH, None),
        ("spending_plan", MessageIntent.SPENDING_PLAN, None),
        ("top_month", MessageIntent.TOP_MONTH, None),
        ("summary", MessageIntent.SUMMARY, None),
        ("period_details", MessageIntent.PERIOD_DETAILS, None),
        ("register", MessageIntent.REGISTER, None),
        ("help", MessageIntent.HELP, None),
        ("income", MessageIntent.INCOME, None),
    ],
)
async def test_classifier_maps_every_label(
    choice: str,
    intent: MessageIntent,
    banking_intent: BankingIntent | None,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(choice=choice))

    router = JevMessageIntentRouter(
        _settings(), http_client=_client(handler)
    )

    decision = await router.classify("qualquer pergunta")

    assert decision is not None
    assert decision.intent is intent
    assert decision.banking_intent is banking_intent


@pytest.mark.parametrize("reply", [_response(), _response(choice="outro")])
async def test_classifier_returns_none_for_missing_or_unknown_choice(
    reply: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply)

    router = JevMessageIntentRouter(
        _settings(), http_client=_client(handler)
    )

    assert await router.classify("qualquer pergunta") is None


async def test_classifier_returns_none_without_a_token() -> None:
    router = JevMessageIntentRouter(_settings(token=None))

    assert await router.classify("qualquer pergunta") is None


class FakeClassifier:
    def __init__(self, decision) -> None:
        self._decision = decision
        self.calls: list[str] = []

    async def classify(self, text: str):
        self.calls.append(text)
        return self._decision


async def test_composite_prefers_the_jev_classifier() -> None:
    classifier = FakeClassifier(
        RoutingDecision(MessageIntent.PERIOD_DETAILS)
    )
    router = CompositeMessageIntentRouter(classifier=classifier)

    decision = await router.route("lançamentos de set/2026")

    assert decision.intent is MessageIntent.PERIOD_DETAILS
    assert classifier.calls == ["lançamentos de set/2026"]


async def test_composite_falls_back_when_the_classifier_abstains() -> None:
    classifier = FakeClassifier(None)
    router = CompositeMessageIntentRouter(classifier=classifier)

    decision = await router.route("quanto gastei com uber esse mês?")

    assert decision.intent is MessageIntent.SPENDING_SEARCH
    assert classifier.calls == ["quanto gastei com uber esse mês?"]


async def test_composite_keeps_help_as_a_cheap_fast_path() -> None:
    classifier = FakeClassifier(None)
    router = CompositeMessageIntentRouter(classifier=classifier)

    decision = await router.route("O que você pode fazer?")

    assert decision.intent is MessageIntent.HELP
    assert classifier.calls == []


async def test_composite_keeps_strong_banking_as_a_cheap_fast_path() -> None:
    classifier = FakeClassifier(None)
    router = CompositeMessageIntentRouter(
        keywords=KeywordIntentRouter(), classifier=classifier
    )

    decision = await router.route("qual meu saldo")

    assert decision.intent is MessageIntent.BANKING
    assert decision.banking_intent is BankingIntent.ACCOUNTS
    assert classifier.calls == []
