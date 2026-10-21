"""Jev-backed expense category classifier.

Jev is a typed decision model served by TypeSafe's native System One API, not
an OpenAI-compatible chat endpoint. The adapter delegates the request to the
shared :class:`SystemOneChoiceClient`, asks a single ``choice`` question and
maps the raw label back to a domain category. It abstains whenever the token is
absent, the provider fails, or the reply is malformed: categorization then
degrades to the keyword map.
"""

from __future__ import annotations

import httpx

from myfinance.config import Settings
from myfinance.domain.categories import Category
from myfinance.infrastructure.parsing.dates import normalize, strip_edges
from myfinance.infrastructure.typesafe.choice import SystemOneChoiceClient

_QUESTION_ID = "category"
_QUESTION_INSTRUCTIONS = "Classifique a despesa na categoria mais adequada."

_CRITERIA: dict[str, str] = {
    "alimentacao": "Mercado, restaurante, almoço, jantar, café, padaria, comida.",
    "transporte": (
        "Combustível, uber, táxi, ônibus, metrô, estacionamento, pedágio."
    ),
    "lazer": "Cinema, bar, show, jogo, viagem, streaming, parque.",
    "saude": (
        "Farmácia, remédio, médico, consulta, exame, dentista, academia, "
        "hospital."
    ),
    "servicos": (
        "Luz, água, internet, telefone, aluguel, energia, gás, assinatura, "
        "condomínio."
    ),
    "outros": "Qualquer despesa que não se encaixe nas categorias acima.",
}

_CATEGORIES: dict[str, Category] = {
    "alimentacao": Category.ALIMENTACAO,
    "transporte": Category.TRANSPORTE,
    "lazer": Category.LAZER,
    "saude": Category.SAUDE,
    "servicos": Category.SERVICOS,
    "outros": Category.OUTROS,
}

_LABELS: dict[str, Category] = {
    normalize(category.label): category for category in Category
}


def _parse_category(raw: str | None) -> Category | None:
    """Map a model reply to a category without trusting its formatting."""
    if not raw:
        return None

    normalized = normalize(strip_edges(raw))
    if not normalized:
        return None

    return _CATEGORIES.get(normalized) or _LABELS.get(normalized)


class JevCategoryClassifier:
    """Classifies expense text through TypeSafe's System One API."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = SystemOneChoiceClient(settings, http_client)

    async def classify(self, text: str) -> Category | None:
        choice = await self._client.choose(
            state=text,
            question_id=_QUESTION_ID,
            instructions=_QUESTION_INSTRUCTIONS,
            criteria=_CRITERIA,
        )
        return _parse_category(choice)
