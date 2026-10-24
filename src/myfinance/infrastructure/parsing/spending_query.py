"""Parsers that turn a spending question into a structured query.

The LLM parser only translates the question into period, category and keywords;
the deterministic parser does the same offline with keyword rules. Neither ever
produces amounts: the numbers are always computed by the application layer.
"""

from __future__ import annotations

import json
from datetime import date

from myfinance.application.dto import SpendingQuery
from myfinance.application.ports import LanguageModel
from myfinance.domain.categories import Category
from myfinance.domain.models import ChatMessage
from myfinance.infrastructure.categorization.keywords import classify_keywords
from myfinance.infrastructure.parsing.dates import normalize, strip_edges

__all__ = [
    "DeterministicSpendingQueryParser",
    "OpenCodeSpendingQueryParser",
]

_ALIMENTACAO_SYNONYMS = frozenset(
    normalize(word) for word in ("alimentos", "alimentacao", "comida")
)

# Merchant/place terms identify the subject, never the whole category: "uber"
# and "posto" must not turn a spending question into all of Transporte.
_MERCHANT_TERMS = frozenset(
    normalize(word)
    for word in ("uber", "posto", "gasolina", "combustivel", "etanol", "diesel")
)

_MONTH_NAMES = frozenset(
    normalize(word)
    for word in (
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    )
)

_STOPWORDS = frozenset(
    normalize(word)
    for word in (
        "quanto",
        "gastei",
        "gasto",
        "gastos",
        "gaste",
        "em",
        "com",
        "no",
        "na",
        "nos",
        "nas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "esse",
        "essa",
        "esta",
        "este",
        "mes",
        "semana",
        "ano",
        "anos",
        "hoje",
        "ontem",
        "amanha",
        "passado",
        "passada",
        "atual",
        "ultimo",
        "ultima",
        "dia",
        "dias",
        "por",
        "para",
        "o",
        "a",
        "os",
        "as",
        "e",
        "que",
        "como",
        "estao",
        "quero",
        "resumo",
        "resume",
        "balanco",
        "ver",
        "mostra",
        "mostrar",
        "mostre",
        "lista",
        "listar",
        "exibe",
        "exibir",
        "me",
        "te",
        "lhe",
        "categoria",
        "categorias",
        "meu",
        "minha",
        "meus",
        "minhas",
        "eu",
        "gente",
        "banco",
        "bancos",
        "conta",
        "contas",
        "cartao",
        "cartoes",
        "compras",
        "compra",
        "comprar",
        "comprei",
        "saldo",
        "saldos",
        "extrato",
        "extratos",
        "transacao",
        "transacoes",
        "pagamento",
        "pagamentos",
        "fatura",
        "faturas",
        "pix",
        "limite",
        "credito",
        "debito",
    )
)


def _spending_query_prompt(today: date) -> str:
    return (
        "Você extrai filtros de perguntas sobre gastos em português do Brasil.\n"
        "Responda APENAS com um objeto JSON válido, sem markdown e sem texto "
        "adicional, exatamente neste formato:\n"
        '{"period_reference": null, "category": null, "keywords": []}\n'
        "Regras:\n"
        "- period_reference: copie a expressão de período dita pelo usuário, "
        "sem traduzir e sem inventar (por exemplo: \"esse mes\", \"em outubro\", "
        "\"semana passada\"); use null quando não houver período.\n"
        "- category: escolha uma entre \"alimentacao\", \"transporte\", "
        "\"lazer\", \"saude\", \"servicos\", \"outros\", ou null quando nenhuma "
        "categoria for mencionada. \"alimentos\" e \"comida\" significam "
        "\"alimentacao\".\n"
        "- keywords: termos de estabelecimento ou lugar citados pelo usuário, "
        "em minúsculas, sem acentos e sem palavras de parada nem expressões de "
        "período. Termos como \"uber\", \"posto\" e \"gasolina\" vão em "
        "keywords e não devem ampliar a categoria para \"transporte\".\n"
        "- Nunca invente valores monetários nem inclua números de valores nas "
        "keywords.\n"
        f"Hoje é {today.isoformat()}."
    )


class OpenCodeSpendingQueryParser:
    """Asks a language model for strict JSON and validates the result."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def parse(self, text: str, *, today: date) -> SpendingQuery | None:
        messages = [
            ChatMessage(role="system", content=_spending_query_prompt(today)),
            ChatMessage(role="user", content=text),
        ]
        raw = await self._model.complete(messages)

        try:
            payload = self._extract_object(raw)
            if not {"period_reference", "category", "keywords"} <= set(payload):
                raise KeyError("missing spending query fields")
            period_reference = _period_reference(payload["period_reference"])
            category = _category(payload["category"])
            keywords = _keywords(payload["keywords"])
        except (
            json.JSONDecodeError,
            ValueError,
            KeyError,
            TypeError,
        ):
            return None

        return SpendingQuery(
            period_reference=period_reference,
            category=category,
            keywords=keywords,
        )

    @staticmethod
    def _extract_object(raw: str) -> dict[str, object]:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end < start:
            raise ValueError("model output has no JSON object")
        payload = json.loads(raw[start : end + 1])
        if not isinstance(payload, dict):
            raise TypeError("model output is not a JSON object")
        return payload


class DeterministicSpendingQueryParser:
    """Extracts the same query offline, with keyword rules only."""

    async def parse(self, text: str, *, today: date) -> SpendingQuery | None:
        if not isinstance(text, str) or not text.strip():
            return None

        tokens = _subject_terms(text)
        terms = set(tokens)
        if terms & _ALIMENTACAO_SYNONYMS:
            return SpendingQuery(
                period_reference=text,
                category=Category.ALIMENTACAO,
                keywords=(),
            )

        if terms & _MERCHANT_TERMS:
            return SpendingQuery(
                period_reference=text,
                category=None,
                keywords=tokens,
            )

        category = classify_keywords(text)
        if category is None and not tokens:
            return None

        return SpendingQuery(
            period_reference=text,
            category=category,
            keywords=tokens,
        )


def _subject_terms(text: str) -> tuple[str, ...]:
    """Return the meaningful words of ``text``, in order and without repeats."""
    terms: list[str] = []
    for raw_token in text.split():
        token = normalize(strip_edges(raw_token))
        if (
            not token
            or token in _STOPWORDS
            or token in _MONTH_NAMES
            or any(character.isdigit() for character in token)
        ):
            continue
        if token not in terms:
            terms.append(token)
    return tuple(terms)


def _period_reference(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("period_reference must be a string or null")
    return value.strip() or None


def _category(value: object) -> Category | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("category must be a string or null")
    return Category(value)


def _keywords(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError("keywords must be a list of strings")
    keywords: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError("keywords must be a list of strings")
        keyword = normalize(item)
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return tuple(keywords)
