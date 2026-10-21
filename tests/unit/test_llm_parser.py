"""Regression tests for the LLM parser and the composite parser."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from myfinance.application.dto import ParsedMessage
from myfinance.application.errors import ProviderError
from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.composite import CompositeMessageParser
from myfinance.infrastructure.parsing.llm import OpenCodeMessageParser

TODAY = date(2026, 10, 20)
USER_TEXT = "jantar ontem 45,50"
CATEGORY_KEYS = (
    "alimentacao",
    "transporte",
    "lazer",
    "saude",
    "servicos",
    "outros",
)


class FakeLanguageModel:
    """Returns a canned completion, or raises a canned error."""

    def __init__(
        self,
        reply: str = "",
        *,
        error: Exception | None = None,
    ) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[Any]] = []

    async def complete(
        self,
        messages: list[Any],
        *,
        session_id: str | None = None,
    ) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.reply


class FakeClassifier:
    """Returns a canned category and records the classified text."""

    def __init__(self, category: Category | None) -> None:
        self.category = category
        self.calls: list[str] = []

    async def classify(self, text: str) -> Category | None:
        self.calls.append(text)
        return self.category


class FakeParser:
    """A MessageParser that returns or raises a canned result."""

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


def json_body(**overrides: object) -> str:
    payload: dict[str, object] = {
        "kind": "expense",
        "amount_cents": 4550,
        "date": "2026-10-19",
        "category": "outros",
        "description": "jantar",
    }
    payload.update(overrides)
    return json.dumps(payload)


def parsed_message() -> ParsedMessage:
    return ParsedMessage(
        kind=EntryKind.EXPENSE,
        amount=Money(4550),
        day=date(2026, 10, 19),
        category=Category.ALIMENTACAO,
        description="jantar",
    )


async def test_classifier_overrides_the_json_category() -> None:
    model = FakeLanguageModel(json_body())
    classifier = FakeClassifier(Category.LAZER)
    parser = OpenCodeMessageParser(model, classifier)

    result = await parser.parse(USER_TEXT, today=TODAY)

    assert result is not None
    assert result.category is Category.LAZER
    assert classifier.calls == [USER_TEXT]


async def test_json_category_is_used_when_no_classifier_is_given() -> None:
    model = FakeLanguageModel(json_body(category="outros"))
    parser = OpenCodeMessageParser(model)

    result = await parser.parse(USER_TEXT, today=TODAY)

    assert result is not None
    assert result.category is Category.OUTROS


async def test_invalid_json_returns_none() -> None:
    model = FakeLanguageModel("isto não é json")
    parser = OpenCodeMessageParser(model)

    assert await parser.parse(USER_TEXT, today=TODAY) is None


async def test_unrecognized_json_category_falls_back_to_the_classifier() -> None:
    model = FakeLanguageModel(json_body(category="banana"))
    classifier = FakeClassifier(Category.SAUDE)
    parser = OpenCodeMessageParser(model, classifier)

    result = await parser.parse(USER_TEXT, today=TODAY)

    assert result is not None
    assert result.category is Category.SAUDE
    assert classifier.calls == [USER_TEXT]


async def test_unrecognized_json_category_without_classifier_returns_none() -> None:
    model = FakeLanguageModel(json_body(category="banana"))
    parser = OpenCodeMessageParser(model)

    assert await parser.parse(USER_TEXT, today=TODAY) is None


async def test_invalid_kind_returns_none_even_with_a_classifier() -> None:
    model = FakeLanguageModel(json_body(kind="transferencia"))
    classifier = FakeClassifier(Category.SAUDE)
    parser = OpenCodeMessageParser(model, classifier)

    assert await parser.parse(USER_TEXT, today=TODAY) is None
    assert classifier.calls == []


async def test_provider_error_propagates_out_of_the_parser() -> None:
    model = FakeLanguageModel(error=ProviderError("provider down"))
    parser = OpenCodeMessageParser(model, FakeClassifier(Category.LAZER))

    with pytest.raises(ProviderError):
        await parser.parse(USER_TEXT, today=TODAY)


async def test_system_prompt_carries_today_and_every_category_key() -> None:
    model = FakeLanguageModel(json_body())
    parser = OpenCodeMessageParser(model)

    await parser.parse(USER_TEXT, today=TODAY)

    system_prompt = model.calls[0][0].content
    assert TODAY.isoformat() in system_prompt
    for key in CATEGORY_KEYS:
        assert key in system_prompt


async def test_composite_returns_the_primary_result_without_the_fallback() -> None:
    primary_result = parsed_message()
    primary = FakeParser(primary_result)
    fallback = FakeParser(parsed_message())
    parser = CompositeMessageParser(primary, fallback)

    result = await parser.parse(USER_TEXT, today=TODAY)

    assert result is primary_result
    assert fallback.calls == []


async def test_composite_uses_the_fallback_when_the_primary_abstains() -> None:
    fallback_result = parsed_message()
    primary = FakeParser(None)
    fallback = FakeParser(fallback_result)
    parser = CompositeMessageParser(primary, fallback)

    result = await parser.parse(USER_TEXT, today=TODAY)

    assert result is fallback_result
    assert fallback.calls == [(USER_TEXT, TODAY)]


async def test_composite_swallows_a_provider_error_from_the_fallback() -> None:
    primary = FakeParser(None)
    fallback = FakeParser(error=ProviderError("provider down"))
    parser = CompositeMessageParser(primary, fallback)

    assert await parser.parse(USER_TEXT, today=TODAY) is None


async def test_composite_returns_none_without_a_fallback() -> None:
    parser = CompositeMessageParser(FakeParser(None))

    assert await parser.parse(USER_TEXT, today=TODAY) is None
