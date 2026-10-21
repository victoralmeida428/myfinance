"""Unit tests for the Jev LLM gate and the gated composite parser."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import httpx2
import pytest

from myfinance.application.dto import ParsedMessage
from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.composite import CompositeMessageParser
from myfinance.infrastructure.parsing.gate import JevLLMGate

TODAY = date(2026, 10, 20)
BASE_URL = "https://api.typesafe.ai"


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        categorizer_api_token="test",
        categorizer_model="jev-latest",
        categorizer_base_url=BASE_URL,
    )


def _response(
    *,
    choice: str | None = None,
    answer: bool = True,
    probabilities: dict[str, float] | None = None,
) -> dict[str, object]:
    answers: dict[str, object] = {}
    if answer:
        payload: dict[str, object] = {"type": "choice", "confidence": 1.0}
        if choice is not None:
            payload["choice"] = choice
        if probabilities is not None:
            payload["probabilities"] = probabilities
        answers["route"] = payload
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def test_gate_sends_the_expected_systemone_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_response(choice="financial"))

    gate = JevLLMGate(_settings(), http_client=_client(handler))
    text = "almoço 45 reais"

    result = await gate.should_use_llm(text)

    assert result is True
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    headers = captured["headers"]
    assert headers["authorization"] == "Bearer test"

    body = captured["body"]
    assert body["model"] == "jev-latest"
    assert body["state"] == text
    question = body["questions"]["route"]
    assert question["type"] == "choice"
    criteria = question["criteria"]
    assert "financial" in criteria
    assert "generic" in criteria


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("financial", True),
        ("generic", False),
    ],
)
async def test_gate_maps_the_choice_answer(
    choice: str, expected: bool
) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_response(choice=choice))

    gate = JevLLMGate(_settings(), http_client=_client(handler))

    assert await gate.should_use_llm("oi") is expected


@pytest.mark.parametrize(
    "reply",
    [
        _response(answer=False),
        _response(choice="outro"),
    ],
)
async def test_gate_returns_none_for_a_missing_or_unknown_choice(
    reply: dict[str, object],
) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=reply)

    gate = JevLLMGate(_settings(), http_client=_client(handler))

    assert await gate.should_use_llm("oi") is None


class FakeParser:
    """A MessageParser that records calls and returns a canned result."""

    def __init__(
        self,
        result: ParsedMessage | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, date]] = []

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None:
        self.calls.append((text, today))
        if self.error is not None:
            raise self.error
        return self.result


class FakeGate:
    """An LLMGate that records calls and returns or raises a canned decision."""

    def __init__(
        self,
        decision: bool | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision
        self.error = error
        self.calls: list[str] = []

    async def should_use_llm(self, text: str) -> bool | None:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.decision


def parsed_message() -> ParsedMessage:
    return ParsedMessage(
        kind=EntryKind.EXPENSE,
        amount=Money(4500),
        day=TODAY,
        category=Category.ALIMENTACAO,
        description="almoço",
    )


async def test_gate_true_uses_the_fallback() -> None:
    fallback_result = parsed_message()
    fallback = FakeParser(fallback_result)
    gate = FakeGate(True)
    parser = CompositeMessageParser(FakeParser(None), fallback, gate)

    result = await parser.parse("almoço", today=TODAY)

    assert result is fallback_result
    assert gate.calls == ["almoço"]
    assert fallback.calls == [("almoço", TODAY)]


async def test_gate_false_blocks_the_fallback_even_with_digits() -> None:
    fallback = FakeParser(parsed_message())
    gate = FakeGate(False)
    parser = CompositeMessageParser(FakeParser(None), fallback, gate)

    result = await parser.parse("meu cpf e 12345678901", today=TODAY)

    assert result is None
    assert gate.calls == ["meu cpf e 12345678901"]
    assert fallback.calls == []


async def test_gate_none_with_digits_uses_the_fallback() -> None:
    fallback_result = parsed_message()
    fallback = FakeParser(fallback_result)
    parser = CompositeMessageParser(FakeParser(None), fallback, FakeGate(None))

    result = await parser.parse("almoço 45", today=TODAY)

    assert result is fallback_result
    assert fallback.calls == [("almoço 45", TODAY)]


async def test_gate_none_without_digits_skips_the_fallback() -> None:
    fallback = FakeParser(parsed_message())
    parser = CompositeMessageParser(FakeParser(None), fallback, FakeGate(None))

    result = await parser.parse("oi tudo bem", today=TODAY)

    assert result is None
    assert fallback.calls == []


async def test_primary_hit_never_calls_the_gate_or_fallback() -> None:
    primary_result = parsed_message()
    fallback = FakeParser(parsed_message())
    gate = FakeGate(True)
    parser = CompositeMessageParser(FakeParser(primary_result), fallback, gate)

    result = await parser.parse("almoço 45", today=TODAY)

    assert result is primary_result
    assert gate.calls == []
    assert fallback.calls == []


async def test_gate_provider_error_falls_back_to_the_digit_heuristic() -> None:
    fallback_result = parsed_message()
    fallback = FakeParser(fallback_result)
    gate = FakeGate(error=ProviderError("provider down"))
    parser = CompositeMessageParser(FakeParser(None), fallback, gate)

    result = await parser.parse("almoço 45", today=TODAY)

    assert result is fallback_result
    assert fallback.calls == [("almoço 45", TODAY)]


async def test_gate_provider_error_without_digits_skips_the_fallback() -> None:
    fallback = FakeParser(parsed_message())
    gate = FakeGate(error=ProviderError("provider down"))
    parser = CompositeMessageParser(FakeParser(None), fallback, gate)

    result = await parser.parse("oi tudo bem", today=TODAY)

    assert result is None
    assert fallback.calls == []
