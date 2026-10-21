"""Unit tests for pt-BR date references and resolution."""

from datetime import date

import pytest

from myfinance.infrastructure.parsing.dates import (
    PortugueseDateResolver,
    find_date_reference,
    strip_edges,
)

TODAY = date(2026, 10, 20)  # a Tuesday


@pytest.fixture
def resolver() -> PortugueseDateResolver:
    return PortugueseDateResolver()


@pytest.mark.parametrize("reference", [None, "", "   "])
def test_missing_reference_means_today(
    resolver: PortugueseDateResolver, reference: str | None
) -> None:
    assert resolver.resolve(reference, today=TODAY) == TODAY


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("hoje", date(2026, 10, 20)),
        ("ontem", date(2026, 10, 19)),
        ("amanhã", date(2026, 10, 21)),
        ("depois de amanhã", date(2026, 10, 22)),
    ],
)
def test_relative_references(
    resolver: PortugueseDateResolver, reference: str, expected: date
) -> None:
    assert resolver.resolve(reference, today=TODAY) == expected


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("2026-10-25", date(2026, 10, 25)),
        ("25/10/2026", date(2026, 10, 25)),
        ("25/10", date(2026, 10, 25)),
    ],
)
def test_absolute_references(
    resolver: PortugueseDateResolver, reference: str, expected: date
) -> None:
    assert resolver.resolve(reference, today=TODAY) == expected


def test_weekday_counts_today_as_the_next_occurrence(
    resolver: PortugueseDateResolver,
) -> None:
    assert resolver.resolve("terça", today=TODAY) == TODAY
    assert resolver.resolve("segunda", today=TODAY) == date(2026, 10, 26)


def test_weekday_accepts_the_feira_suffix(
    resolver: PortugueseDateResolver,
) -> None:
    assert resolver.resolve("segunda-feira", today=TODAY) == date(2026, 10, 26)


@pytest.mark.parametrize("reference", ["banana", "32/13", "32/13/2026"])
def test_unknown_or_invalid_references_return_none(
    resolver: PortugueseDateResolver, reference: str
) -> None:
    assert resolver.resolve(reference, today=TODAY) is None


def test_find_date_reference_reports_hoje_at_index_zero() -> None:
    found = find_date_reference(["hoje"])

    assert found is not None
    reference, indexes = found
    assert reference == "hoje"
    assert indexes == frozenset({0})


def test_find_date_reference_consumes_three_words_for_depois_de_amanha() -> None:
    found = find_date_reference(["depois", "de", "amanhã"])

    assert found is not None
    reference, indexes = found
    assert reference == "depois de amanha"
    assert indexes == frozenset({0, 1, 2})
    assert len(indexes) == 3


def test_find_date_reference_normalizes_segunda_feira() -> None:
    found = find_date_reference(["segunda-feira"])

    assert found is not None
    assert found[0] == "segunda"


@pytest.mark.parametrize("token", ["25/10", "2026-10-25"])
def test_find_date_reference_returns_numeric_dates_as_is(token: str) -> None:
    found = find_date_reference([token])

    assert found is not None
    assert found[0] == token


def test_find_date_reference_without_a_date_returns_none() -> None:
    assert find_date_reference(["oi", "tudo", "bem"]) is None


def test_strip_edges_keeps_internal_separators() -> None:
    assert strip_edges("25/10") == "25/10"
    assert strip_edges("2026-10-25") == "2026-10-25"
    assert strip_edges("(hoje)") == "hoje"
    assert strip_edges("...mercado,") == "mercado"
