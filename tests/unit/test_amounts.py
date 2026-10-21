"""Unit tests for pt-BR amount extraction and parsing."""

import pytest

from myfinance.infrastructure.parsing.amounts import (
    find_amount,
    parse_amount_cents,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("80", 8000),
        ("R$ 80", 8000),
        ("80,50", 8050),
        ("1.234,56", 123456),
        ("1.234", 123400),
        ("80.50", 8050),
        ("R$1.234,56", 123456),
    ],
)
def test_parse_amount_cents_accepts_pt_br_notation(
    raw: str, expected: int
) -> None:
    assert parse_amount_cents(raw) == expected


@pytest.mark.parametrize("raw", ["0", "abc", "-10", "", "1.2.3"])
def test_parse_amount_cents_rejects_invalid_input(raw: str) -> None:
    assert parse_amount_cents(raw) is None


def test_find_amount_locates_the_value_in_a_sentence() -> None:
    match = find_amount("gastei 45 no mercado")

    assert match is not None
    assert "45" in match.group(0)
