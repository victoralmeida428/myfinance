"""Jev-backed gate deciding whether a message should reach the LLM fallback.

The deterministic parser has already abstained by the time this gate runs.
Jev answers one typed ``choice`` question through TypeSafe's System One API;
the raw label is mapped to a tri-state decision so callers can fall back to
their own heuristic when the model abstains or is unavailable.
"""

from __future__ import annotations

import httpx

from myfinance.config import Settings
from myfinance.infrastructure.parsing.dates import normalize, strip_edges
from myfinance.infrastructure.typesafe.choice import SystemOneChoiceClient

_QUESTION_ID = "route"
_QUESTION_INSTRUCTIONS = (
    "Decida se a mensagem é um lançamento financeiro (gasto ou previsão) que "
    "precisa extrair valor e data, ou uma mensagem genérica."
)

_CRITERIA: dict[str, str] = {
    "financial": (
        "Registrar gasto, despesa, compra, previsão, orçamento, valor ou data."
    ),
    "generic": (
        "Saudação, agradecimento, conversa, ajuda, ou qualquer mensagem sem "
        "intenção de registrar um lançamento."
    ),
}

_DECISIONS: dict[str, bool] = {
    "financial": True,
    "generic": False,
}


def _parse_decision(raw: str | None) -> bool | None:
    """Map a model reply to a tri-state decision without trusting formatting."""
    if not raw:
        return None

    normalized = normalize(strip_edges(raw))
    return _DECISIONS.get(normalized)


class JevLLMGate:
    """Decides through TypeSafe's System One API whether to use the LLM."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = SystemOneChoiceClient(settings, http_client)

    async def should_use_llm(self, text: str) -> bool | None:
        choice = await self._client.choose(
            state=text,
            question_id=_QUESTION_ID,
            instructions=_QUESTION_INSTRUCTIONS,
            criteria=_CRITERIA,
        )
        return _parse_decision(choice)
