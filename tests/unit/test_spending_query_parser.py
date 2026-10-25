"""Regression tests for the LLM and deterministic spending query parsers."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from myfinance.application.dto import SpendingQuery
from myfinance.application.errors import ProviderError
from myfinance.domain.categories import Category
from myfinance.infrastructure.parsing.spending_query import (
    DeterministicSpendingQueryParser,
    OpenCodeSpendingQueryParser,
)

TODAY = date(2026, 10, 20)
UBER_TEXT = "quanto gastei com uber esse mes"
FOOD_TEXT = "quanto gastei com alimentos"
POSTO_TEXT = "quanto em posto de gasolina"


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


def query_body(**overrides: object) -> str:
    payload: dict[str, object] = {
        "period_reference": None,
        "category": None,
        "keywords": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


async def test_llm_extracts_period_and_merchant_keywords() -> None:
    model = FakeLanguageModel(
        query_body(
            period_reference="esse mes",
            category=None,
            keywords=["uber"],
        )
    )
    parser = OpenCodeSpendingQueryParser(model)

    result = await parser.parse(UBER_TEXT, today=TODAY)

    assert result == SpendingQuery(
        period_reference="esse mes",
        category=None,
        keywords=("uber",),
    )


async def test_llm_keeps_the_raw_user_message_and_today_context() -> None:
    model = FakeLanguageModel(query_body(period_reference="esse mes"))
    parser = OpenCodeSpendingQueryParser(model)

    await parser.parse(UBER_TEXT, today=TODAY)

    assert model.calls[0][-1].content == UBER_TEXT
    assert TODAY.isoformat() in model.calls[0][0].content


async def test_llm_maps_alimentos_to_the_food_category() -> None:
    model = FakeLanguageModel(query_body(category="alimentacao"))
    parser = OpenCodeSpendingQueryParser(model)

    result = await parser.parse(FOOD_TEXT, today=TODAY)

    assert result == SpendingQuery(
        period_reference=None,
        category=Category.ALIMENTACAO,
        keywords=(),
    )


async def test_llm_keeps_posto_as_keyword_without_a_category() -> None:
    model = FakeLanguageModel(query_body(keywords=["posto"]))
    parser = OpenCodeSpendingQueryParser(model)

    result = await parser.parse(POSTO_TEXT, today=TODAY)

    assert result is not None
    assert result.category is None
    assert result.keywords == ("posto",)


async def test_llm_normalizes_keywords_to_lowercase_without_accents() -> None:
    model = FakeLanguageModel(query_body(keywords=["POSTO", "Combustível", "posto"]))
    parser = OpenCodeSpendingQueryParser(model)

    result = await parser.parse(POSTO_TEXT, today=TODAY)

    assert result is not None
    assert result.keywords == ("posto", "combustivel")


@pytest.mark.parametrize(
    "reply",
    [
        "isto não é json",
        '{"period_reference": "esse mes", "category": "alimentacao"}',
        query_body(category="banana"),
        query_body(keywords="posto"),
        query_body(keywords=[1, 2]),
        query_body(period_reference=42),
        "",
    ],
)
async def test_llm_returns_none_for_malformed_output(reply: str) -> None:
    parser = OpenCodeSpendingQueryParser(FakeLanguageModel(reply))

    assert await parser.parse(UBER_TEXT, today=TODAY) is None


async def test_llm_rejects_a_query_without_category_or_keywords() -> None:
    parser = OpenCodeSpendingQueryParser(
        FakeLanguageModel(query_body(period_reference="essa semana"))
    )

    assert await parser.parse("resumo da semana", today=TODAY) is None


async def test_llm_provider_error_propagates() -> None:
    parser = OpenCodeSpendingQueryParser(
        FakeLanguageModel(error=ProviderError("provider down"))
    )

    with pytest.raises(ProviderError):
        await parser.parse(UBER_TEXT, today=TODAY)


async def test_deterministic_maps_alimentos_to_food_without_keywords() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse(FOOD_TEXT, today=TODAY)

    assert result == SpendingQuery(
        period_reference=FOOD_TEXT,
        category=Category.ALIMENTACAO,
        keywords=(),
    )


async def test_deterministic_maps_comida_to_food() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse("quanto gastei com comida ontem", today=TODAY)

    assert result is not None
    assert result.category is Category.ALIMENTACAO
    assert result.keywords == ()


async def test_deterministic_keeps_uber_as_keyword_without_transporte() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse(UBER_TEXT, today=TODAY)

    assert result == SpendingQuery(
        period_reference=UBER_TEXT,
        category=None,
        keywords=("uber",),
    )


async def test_deterministic_keeps_posto_and_gasolina_without_transporte() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse(POSTO_TEXT, today=TODAY)

    assert result is not None
    assert result.category is None
    assert result.keywords == ("posto", "gasolina")


async def test_deterministic_uses_classify_keywords_for_a_plain_subject() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse("quanto gastei com mercado", today=TODAY)

    assert result is not None
    assert result.category is Category.ALIMENTACAO
    assert result.keywords == ("mercado",)


async def test_deterministic_drops_banking_words_from_keywords() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse(
        "quanto gastei com uber e compras?", today=TODAY
    )

    assert result is not None
    assert result.category is None
    assert result.keywords == ("uber",)


async def test_deterministic_returns_none_without_a_subject() -> None:
    parser = DeterministicSpendingQueryParser()

    assert await parser.parse("quanto gastei hoje?", today=TODAY) is None


async def test_deterministic_returns_none_for_blank_text() -> None:
    parser = DeterministicSpendingQueryParser()

    assert await parser.parse("   ", today=TODAY) is None


async def test_deterministic_drops_year_word_from_keywords() -> None:
    parser = DeterministicSpendingQueryParser()

    result = await parser.parse(
        "quanto gastei de gasolina esse ano?", today=TODAY
    )

    assert result is not None
    assert result.period_reference == "quanto gastei de gasolina esse ano?"
    assert result.keywords == ("gasolina",)
