"""Deterministic, rule-based parser for short pt-BR messages.

No I/O and no language model: it tokenizes the message, removes a date and an
amount, then classifies the remaining words. Used as the primary parser so the
common cases are fast, predictable and free.
"""

from __future__ import annotations

from datetime import date

from myfinance.application.dto import ParsedMessage
from myfinance.application.ports import CategoryClassifier
from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.categorization.keywords import classify_keywords
from myfinance.infrastructure.parsing.amounts import find_amount, parse_amount_cents
from myfinance.infrastructure.parsing.dates import (
    PortugueseDateResolver,
    find_date_reference,
    normalize,
    strip_edges,
)


def _keywords(*words: str) -> frozenset[str]:
    return frozenset(normalize(word) for word in words)


_FORECAST_KEYWORDS = _keywords(
    "pretendo",
    "previsao",
    "planejo",
    "planejei",
    "orcamento",
    "reservar",
    "reservei",
    "estimo",
    "estimativa",
)
_EXPENSE_KEYWORDS = _keywords(
    "gastei",
    "paguei",
    "deu",
    "comprei",
    "custou",
    "custo",
    "saiu",
)
_FORECAST_PHRASE = ("vou", "gastar")

_CONNECTIVES = _keywords(
    "de",
    "do",
    "da",
    "dos",
    "das",
    "no",
    "na",
    "nos",
    "nas",
    "em",
    "para",
    "por",
    "com",
)
_KIND_VERBS = _FORECAST_KEYWORDS | _EXPENSE_KEYWORDS | _keywords(
    "gastar",
    "gasto",
    "gastos",
)


def _has_phrase(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    length = len(phrase)
    return any(
        tuple(tokens[index : index + length]) == phrase
        for index in range(len(tokens) - length + 1)
    )


class DeterministicMessageParser:
    """Parses messages with dates, amounts and keyword heuristics."""

    def __init__(
        self,
        dates: PortugueseDateResolver,
        classifier: CategoryClassifier | None = None,
    ) -> None:
        self._dates = dates
        self._classifier = classifier

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None:
        if not isinstance(text, str) or not text.strip():
            return None

        tokens = text.split()
        cleaned = [strip_edges(token) for token in tokens]
        normalized = [normalize(token) for token in cleaned]

        day, date_indexes = self._find_date(cleaned, today)

        kept = [
            cleaned[index]
            for index in range(len(cleaned))
            if index not in date_indexes
        ]
        amount_source = " ".join(kept)

        match = find_amount(amount_source)
        if match is None:
            return None

        cents = parse_amount_cents(match.group(0))
        if cents is None:
            return None

        kind = self._kind(normalized)
        description = _description(
            f"{amount_source[: match.start()]} {amount_source[match.end() :]}"
        )
        category = (
            await self._classifier.classify(text)
            if self._classifier is not None
            else None
        )
        if category is None:
            category = classify_keywords(text) or Category.OUTROS

        return ParsedMessage(
            kind=kind,
            amount=Money(cents),
            day=day,
            category=category,
            description=description or category.label,
        )

    def _find_date(
        self,
        cleaned: list[str],
        today: date,
    ) -> tuple[date, set[int]]:
        found = find_date_reference(cleaned)
        if found is None:
            return today, set()

        reference, consumed = found
        day = self._dates.resolve(reference, today=today)
        if day is None:
            return today, set()

        return day, set(consumed)

    @staticmethod
    def _kind(normalized: list[str]) -> EntryKind:
        tokens = set(normalized)
        if tokens & _FORECAST_KEYWORDS or _has_phrase(normalized, _FORECAST_PHRASE):
            return EntryKind.FORECAST
        if tokens & _EXPENSE_KEYWORDS:
            return EntryKind.EXPENSE
        return EntryKind.EXPENSE


def _description(source: str) -> str:
    words = [word for word in (strip_edges(token) for token in source.split()) if word]
    normalized = [normalize(word) for word in words]

    dropped = {
        index for index, token in enumerate(normalized) if token in _KIND_VERBS
    }
    for index in range(len(normalized) - 1):
        if (normalized[index], normalized[index + 1]) == _FORECAST_PHRASE:
            dropped.update((index, index + 1))

    remaining = [
        word for index, word in enumerate(words) if index not in dropped
    ]
    remaining_normalized = [normalize(word) for word in remaining]

    start = 0
    end = len(remaining)
    while start < end and remaining_normalized[start] in _CONNECTIVES:
        start += 1
    while end > start and remaining_normalized[end - 1] in _CONNECTIVES:
        end -= 1

    return " ".join(remaining[start:end])
