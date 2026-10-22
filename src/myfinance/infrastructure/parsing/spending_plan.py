"""Narrator that wraps already computed spending-plan numbers in advice.

The model only writes prose: every number comes from the application layer and
is supplied in the user prompt as structured data.
"""

from __future__ import annotations

import json

from myfinance.application.dto import SpendingPlanMessage
from myfinance.application.ports import LanguageModel
from myfinance.domain.models import ChatMessage

__all__ = ["OpenCodeSpendingPlanNarrator"]

_SYSTEM_PROMPT = (
    "Você é um assistente financeiro pessoal. Responda em português do "
    "Brasil, em no máximo três frases curtas, com conselhos práticos de "
    "economia baseados APENAS nos números fornecidos. Nunca invente valores, "
    "categorias ou estabelecimentos. Cite explicitamente os principais cortes "
    "e a meta de economia."
)


class OpenCodeSpendingPlanNarrator:
    """Asks a language model for a short narrative around a spending plan."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def narrate(self, plan: SpendingPlanMessage) -> str | None:
        messages = (
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_plan_payload(plan)),
        )
        raw = await self._model.complete(messages)
        narrative = raw.strip()
        return narrative or None


def _plan_payload(plan: SpendingPlanMessage) -> str:
    return json.dumps(
        {
            "total_cents": plan.total_cents,
            "previous_total_cents": plan.previous_total_cents,
            "target_cents": plan.target_cents,
            "categories": [
                {
                    "category": category.category.value,
                    "label": category.category.label,
                    "total_cents": category.total_cents,
                    "share_percent": category.share_percent,
                    "previous_cents": category.previous_cents,
                    "delta_percent": category.delta_percent,
                }
                for category in plan.categories
            ],
            "merchants": [
                {
                    "name": merchant.name,
                    "total_cents": merchant.total_cents,
                    "count": merchant.count,
                }
                for merchant in plan.merchants
            ],
            "cuts": [
                {
                    "label": cut.label,
                    "current_cents": cut.current_cents,
                    "cut_cents": cut.cut_cents,
                }
                for cut in plan.cuts
            ],
        },
        ensure_ascii=False,
    )
