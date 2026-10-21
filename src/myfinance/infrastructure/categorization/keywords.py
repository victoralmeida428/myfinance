"""Keyword-based expense category classification.

The keyword map is the deterministic baseline: it is free, offline and always
available, so the bot keeps categorizing even without an API key.
"""

from __future__ import annotations

from myfinance.domain.categories import Category
from myfinance.infrastructure.parsing.dates import normalize, strip_edges


def _keywords(*words: str) -> frozenset[str]:
    return frozenset(normalize(word) for word in words)


CATEGORY_KEYWORDS: tuple[tuple[Category, frozenset[str]], ...] = (
    (
        Category.ALIMENTACAO,
        _keywords(
            "mercado",
            "supermercado",
            "almoco",
            "jantar",
            "lanche",
            "cafe",
            "padaria",
            "restaurante",
            "ifood",
            "comida",
            "feira",
            "acougue",
            "pizzaria",
        ),
    ),
    (
        Category.TRANSPORTE,
        _keywords(
            "combustivel",
            "gasolina",
            "etanol",
            "diesel",
            "uber",
            "taxi",
            "onibus",
            "metro",
            "estacionamento",
            "pedagio",
            "transporte",
            "passagem",
        ),
    ),
    (
        Category.LAZER,
        _keywords(
            "cinema",
            "bar",
            "show",
            "jogo",
            "viagem",
            "lazer",
            "streaming",
            "netflix",
            "spotify",
            "parque",
        ),
    ),
    (
        Category.SAUDE,
        _keywords(
            "farmacia",
            "remedio",
            "medico",
            "consulta",
            "exame",
            "dentista",
            "academia",
            "saude",
            "hospital",
        ),
    ),
    (
        Category.SERVICOS,
        _keywords(
            "luz",
            "agua",
            "internet",
            "telefone",
            "celular",
            "conta",
            "aluguel",
            "energia",
            "gas",
            "assinatura",
            "condominio",
        ),
    ),
)


def classify_keywords(text: str) -> Category | None:
    """Return the first category whose keywords appear in ``text``.

    Matching is case- and accent-insensitive. Returns ``None`` when nothing
    matches so callers can decide between a smarter classifier and ``OUTROS``.
    """
    tokens = {
        normalized
        for normalized in (
            normalize(strip_edges(token)) for token in text.split()
        )
        if normalized
    }
    for category, keywords in CATEGORY_KEYWORDS:
        if tokens & keywords:
            return category
    return None


class KeywordCategoryClassifier:
    """Category classifier that only looks at the keyword map."""

    async def classify(self, text: str) -> Category | None:
        return classify_keywords(text)
