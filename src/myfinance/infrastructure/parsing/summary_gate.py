"""Jev-backed gate deciding whether a message asks for a summary.

Jev answers one typed ``choice`` question through TypeSafe's System One API;
the raw label is mapped to a tri-state decision so callers can fall back to
their own heuristic when the model abstains or is unavailable.
"""

from __future__ import annotations

import httpx

from myfinance.config import Settings
from myfinance.infrastructure.parsing.dates import normalize, strip_edges
from myfinance.infrastructure.typesafe.choice import SystemOneChoiceClient

_QUESTION_ID = "intent"
_QUESTION_INSTRUCTIONS = (
    "Decida se a mensagem pede um resumo/balanço de gastos ou previsões, ou se "
    "é outro tipo de mensagem."
)

_CRITERIA: dict[str, str] = {
    "summary": (
        "Pedido de resumo de gastos ou previsões: quanto gastei ou planejei, "
        "como estão meus gastos, balanço, resumo do dia, da semana ou do mês."
    ),
    "other": (
        "Registrar gasto ou previsão, consultar saldo, extrato, contas ou dados "
        "bancários, saudação, ajuda, conversa, ou qualquer outro assunto."
    ),
}

_DECISIONS: dict[str, bool] = {
    "summary": True,
    "other": False,
}


def _parse_decision(raw: str | None) -> bool | None:
    """Map a model reply to a tri-state decision without trusting formatting."""
    if not raw:
        return None

    normalized = normalize(strip_edges(raw))
    return _DECISIONS.get(normalized)


class JevSummaryIntentGate:
    """Decides through TypeSafe's System One API whether a summary is wanted."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = SystemOneChoiceClient(settings, http_client)

    async def should_summarize(self, text: str) -> bool | None:
        choice = await self._client.choose(
            state=text,
            question_id=_QUESTION_ID,
            instructions=_QUESTION_INSTRUCTIONS,
            criteria=_CRITERIA,
        )
        return _parse_decision(choice)
