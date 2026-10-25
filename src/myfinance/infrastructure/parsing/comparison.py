"""Narrator that turns a computed comparison into natural Portuguese."""

from __future__ import annotations

import json

from myfinance.application.dto import SpendingComparisonMessage
from myfinance.application.ports import LanguageModel
from myfinance.domain.models import ChatMessage

__all__ = ["OpenCodeSpendingComparisonNarrator"]

_SYSTEM_PROMPT = (
    "Você é um assistente financeiro pessoal. Responda em português do "
    "Brasil, em no máximo três frases curtas. Compare os dois valores "
    "fornecidos, diga se o gasto aumentou ou diminuiu e cite a diferença em "
    "reais e, quando houver, em percentual. Use APENAS os números fornecidos "
    "e nunca invente valores, categorias ou estabelecimentos."
)


class OpenCodeSpendingComparisonNarrator:
    """Asks the model for a short narrative around a computed comparison."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def narrate(
        self, comparison: SpendingComparisonMessage
    ) -> str | None:
        messages = (
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(
                role="user", content=_comparison_payload(comparison)
            ),
        )
        raw = await self._model.complete(messages)
        narrative = raw.strip()
        return narrative or None


def _comparison_payload(comparison: SpendingComparisonMessage) -> str:
    return json.dumps(
        {
            "label": comparison.label,
            "current_period": {
                "start": comparison.current_start.isoformat(),
                "end": comparison.current_end.isoformat(),
                "total_cents": comparison.current_total_cents,
                "count": comparison.current_count,
            },
            "previous_period": {
                "start": comparison.previous_start.isoformat(),
                "end": comparison.previous_end.isoformat(),
                "total_cents": comparison.previous_total_cents,
                "count": comparison.previous_count,
            },
            "delta_cents": comparison.delta_cents,
            "delta_percent": comparison.delta_percent,
        },
        ensure_ascii=False,
    )
