"""Regression tests for OpenCode rate limiting and fallback call reduction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx2
import pytest
from openai import AsyncOpenAI

from myfinance.application.dto import ParsedMessage
from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.domain.models import ChatMessage
from myfinance.domain.money import Money
from myfinance.infrastructure.opencode import OpenCodeLanguageModel
from myfinance.infrastructure.parsing.composite import CompositeMessageParser

TODAY = date(2026, 10, 20)
BASE_URL = "https://example.test/v1"


def build_model(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[OpenCodeLanguageModel, dict[str, int]]:
    """Build a model wired to an in-memory transport that counts requests."""
    counts = {"requests": 0}

    def counting_handler(request: httpx2.Request) -> httpx2.Response:
        counts["requests"] += 1
        return handler(request)

    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(counting_handler),
    )
    settings = Settings(
        _env_file=None,
        opencode_api_key="test",
        opencode_base_url=BASE_URL,
    )
    model = OpenCodeLanguageModel(settings)
    model._client = _async_openai(client)
    return model, counts


def _async_openai(client: httpx2.AsyncClient) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=BASE_URL,
        api_key="test",
        http_client=client,
        max_retries=0,
    )


def rate_limited(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        429,
        json={
            "error": {
                "message": "rate limited",
                "type": "rate_limit_error",
                "code": "rate_limit",
            }
        },
    )


def successful(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
        },
    )


async def test_rate_limit_raises_provider_error_without_sdk_retries() -> None:
    model, counts = build_model(rate_limited)

    with pytest.raises(ProviderError):
        await model.complete([ChatMessage(role="user", content="oi 45")])

    assert counts["requests"] == 1


async def test_second_call_is_blocked_by_the_circuit_breaker() -> None:
    model, counts = build_model(rate_limited)

    with pytest.raises(ProviderError):
        await model.complete([ChatMessage(role="user", content="oi 45")])

    with pytest.raises(ProviderError):
        await model.complete([ChatMessage(role="user", content="oi 45")])

    assert counts["requests"] == 1


async def test_successful_completion_returns_the_content() -> None:
    model, counts = build_model(successful)

    result = await model.complete([ChatMessage(role="user", content="oi 45")])

    assert result == "OK"
    assert counts["requests"] == 1


class CountingParser:
    """A MessageParser that records calls and returns a canned result."""

    def __init__(self, result: ParsedMessage | None = None) -> None:
        self.result = result
        self.calls: list[tuple[str, date]] = []

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None:
        self.calls.append((text, today))
        return self.result


def parsed_message() -> ParsedMessage:
    return ParsedMessage(
        kind=EntryKind.EXPENSE,
        amount=Money(4500),
        day=TODAY,
        category=Category.ALIMENTACAO,
        description="almoço",
    )


async def test_composite_skips_the_fallback_without_digits() -> None:
    fallback = CountingParser(parsed_message())
    parser = CompositeMessageParser(CountingParser(None), fallback)

    result = await parser.parse("oi tudo bem", today=TODAY)

    assert result is None
    assert fallback.calls == []


async def test_composite_uses_the_fallback_when_digits_are_present() -> None:
    fallback_result = parsed_message()
    fallback = CountingParser(fallback_result)
    parser = CompositeMessageParser(CountingParser(None), fallback)

    result = await parser.parse("almoço 45", today=TODAY)

    assert result is fallback_result
    assert fallback.calls == [("almoço 45", TODAY)]


async def test_composite_never_calls_the_fallback_after_a_primary_hit() -> None:
    primary_result = parsed_message()
    fallback = CountingParser(parsed_message())
    parser = CompositeMessageParser(CountingParser(primary_result), fallback)

    result = await parser.parse("almoço 45", today=TODAY)

    assert result is primary_result
    assert fallback.calls == []
