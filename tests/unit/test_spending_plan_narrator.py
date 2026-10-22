"""Unit tests for the spending-plan narrator adapter."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from myfinance.application.dto import (
    CategoryPlan,
    CutSuggestion,
    MerchantSpend,
    SpendingPlanMessage,
)
from myfinance.application.errors import ProviderError
from myfinance.domain.categories import Category
from myfinance.infrastructure.parsing.spending_plan import (
    OpenCodeSpendingPlanNarrator,
)


class FakeLanguageModel:
    def __init__(
        self, reply: str = "", *, error: Exception | None = None
    ) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[Any]] = []

    async def complete(
        self, messages: list[Any], *, session_id: str | None = None
    ) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.reply


def make_plan() -> SpendingPlanMessage:
    return SpendingPlanMessage(
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        total_cents=49000,
        count=7,
        previous_total_cents=32000,
        categories=(
            CategoryPlan(
                category=Category.TRANSPORTE,
                total_cents=20000,
                share_percent=41,
                previous_cents=10000,
                delta_percent=100,
            ),
            CategoryPlan(
                category=Category.ALIMENTACAO,
                total_cents=15000,
                share_percent=31,
                previous_cents=8000,
                delta_percent=88,
            ),
        ),
        merchants=(
            MerchantSpend(name="drogaria nova valqueir", total_cents=15000, count=2),
        ),
        target_cents=4900,
        cuts=(
            CutSuggestion(
                label="Transporte", current_cents=20000, cut_cents=2450
            ),
            CutSuggestion(
                label="Alimentação", current_cents=15000, cut_cents=1838
            ),
        ),
        narrative=None,
    )


async def test_narrative_returns_the_trimmed_model_answer() -> None:
    narrator = OpenCodeSpendingPlanNarrator(
        FakeLanguageModel("  Corte transporte e lazer.  ")
    )

    narrative = await narrator.narrate(make_plan())

    assert narrative == "Corte transporte e lazer."


async def test_user_prompt_carries_exactly_the_computed_numbers() -> None:
    model = FakeLanguageModel("narrativa")
    narrator = OpenCodeSpendingPlanNarrator(model)

    await narrator.narrate(make_plan())

    payload = json.loads(model.calls[0][1].content)
    assert payload["total_cents"] == 49000
    assert payload["previous_total_cents"] == 32000
    assert payload["target_cents"] == 4900
    assert payload["categories"] == [
        {
            "category": "transporte",
            "label": "Transporte",
            "total_cents": 20000,
            "share_percent": 41,
            "previous_cents": 10000,
            "delta_percent": 100,
        },
        {
            "category": "alimentacao",
            "label": "Alimentação",
            "total_cents": 15000,
            "share_percent": 31,
            "previous_cents": 8000,
            "delta_percent": 88,
        },
    ]
    assert payload["merchants"] == [
        {
            "name": "drogaria nova valqueir",
            "total_cents": 15000,
            "count": 2,
        }
    ]
    assert payload["cuts"] == [
        {"label": "Transporte", "current_cents": 20000, "cut_cents": 2450},
        {"label": "Alimentação", "current_cents": 15000, "cut_cents": 1838},
    ]


async def test_system_prompt_forbids_inventing_values() -> None:
    model = FakeLanguageModel("narrativa")
    narrator = OpenCodeSpendingPlanNarrator(model)

    await narrator.narrate(make_plan())

    system_prompt = model.calls[0][0].content
    assert "português do Brasil" in system_prompt
    assert "Nunca invente valores" in system_prompt
    assert "meta de economia" in system_prompt


async def test_blank_model_answer_returns_none() -> None:
    narrator = OpenCodeSpendingPlanNarrator(FakeLanguageModel("   "))

    assert await narrator.narrate(make_plan()) is None


async def test_provider_error_propagates() -> None:
    narrator = OpenCodeSpendingPlanNarrator(
        FakeLanguageModel(error=ProviderError("provider down"))
    )

    with pytest.raises(ProviderError):
        await narrator.narrate(make_plan())
