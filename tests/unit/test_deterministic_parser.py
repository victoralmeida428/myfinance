"""Unit tests for the deterministic, rule-based message parser."""

from datetime import date

import pytest

from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver

TODAY = date(2026, 10, 20)  # a Tuesday


class FakeClassifier:
    """A category classifier with a canned answer, including ``None``."""

    def __init__(self, category: Category | None) -> None:
        self._category = category
        self.calls: list[str] = []

    async def classify(self, text: str) -> Category | None:
        self.calls.append(text)
        return self._category


def make_parser(classifier: FakeClassifier | None = None) -> DeterministicMessageParser:
    return DeterministicMessageParser(PortugueseDateResolver(), classifier)


async def test_parses_a_forecast_with_relative_date() -> None:
    parsed = await make_parser().parse(
        "Amanhã pretendo gastar 80 no mercado", today=TODAY
    )

    assert parsed is not None
    assert parsed.kind is EntryKind.FORECAST
    assert parsed.amount.cents == 8000
    assert parsed.day == date(2026, 10, 21)
    assert parsed.category is Category.ALIMENTACAO
    assert parsed.description == "mercado"


async def test_parses_an_expense_today() -> None:
    parsed = await make_parser().parse("Almoço hoje deu 45", today=TODAY)

    assert parsed is not None
    assert parsed.kind is EntryKind.EXPENSE
    assert parsed.amount.cents == 4500
    assert parsed.day == TODAY
    assert parsed.category is Category.ALIMENTACAO
    assert parsed.description == "Almoço"


async def test_parses_a_forecast_with_transport_keyword() -> None:
    parsed = await make_parser().parse(
        "Previsão de 50 de combustível hoje", today=TODAY
    )

    assert parsed is not None
    assert parsed.kind is EntryKind.FORECAST
    assert parsed.amount.cents == 5000
    assert parsed.day == TODAY
    assert parsed.category is Category.TRANSPORTE
    assert parsed.description == "combustível"


async def test_parses_a_health_expense_and_keeps_trailing_words() -> None:
    parsed = await make_parser().parse(
        "Paguei 30 de farmácia agora", today=TODAY
    )

    assert parsed is not None
    assert parsed.kind is EntryKind.EXPENSE
    assert parsed.amount.cents == 3000
    assert parsed.day == TODAY
    assert parsed.category is Category.SAUDE
    assert parsed.description == "farmácia agora"


async def test_parses_a_short_expense_without_a_verb() -> None:
    parsed = await make_parser().parse("Uber 25", today=TODAY)

    assert parsed is not None
    assert parsed.kind is EntryKind.EXPENSE
    assert parsed.category is Category.TRANSPORTE
    assert parsed.amount.cents == 2500
    assert parsed.day == TODAY


async def test_parses_a_weekday_date() -> None:
    parsed = await make_parser().parse("Cinema sábado 60", today=TODAY)

    assert parsed is not None
    assert parsed.category is Category.LAZER
    assert parsed.amount.cents == 6000
    assert parsed.day == date(2026, 10, 24)


@pytest.mark.parametrize("text", ["oi tudo bem", "gastei zero"])
async def test_messages_without_a_valid_amount_are_rejected(text: str) -> None:
    assert await make_parser().parse(text, today=TODAY) is None


async def test_injected_classifier_overrides_keyword_matching() -> None:
    classifier = FakeClassifier(Category.LAZER)

    parsed = await make_parser(classifier).parse("mercado 45", today=TODAY)

    assert parsed is not None
    assert parsed.category is Category.LAZER
    assert classifier.calls == ["mercado 45"]


async def test_injected_classifier_abstention_falls_back_to_keywords() -> None:
    classifier = FakeClassifier(None)

    parsed = await make_parser(classifier).parse("mercado 45", today=TODAY)

    assert parsed is not None
    assert parsed.category is Category.ALIMENTACAO
    assert classifier.calls == ["mercado 45"]


async def test_unknown_text_falls_back_to_outros() -> None:
    parsed = await make_parser().parse("xyz 10", today=TODAY)

    assert parsed is not None
    assert parsed.category is Category.OUTROS
