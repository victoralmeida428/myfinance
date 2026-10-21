"""Unit tests for the Money value object."""

from decimal import Decimal

import pytest

from myfinance.domain.exceptions import InvalidAmount
from myfinance.domain.money import Money


def test_money_accepts_positive_cents() -> None:
    money = Money(1)

    assert money.cents == 1


@pytest.mark.parametrize("cents", [0, -1])
def test_money_rejects_non_positive_cents(cents: int) -> None:
    with pytest.raises(InvalidAmount):
        Money(cents)


def test_money_rejects_bool_even_though_bool_is_an_int() -> None:
    with pytest.raises(InvalidAmount):
        Money(True)


def test_from_reais_rounds_half_up_to_cents() -> None:
    assert Money.from_reais(Decimal("0.005")).cents == 1


def test_from_reais_converts_whole_reais() -> None:
    assert Money.from_reais(Decimal("45.00")).cents == 4500


def test_from_reais_rejects_zero() -> None:
    with pytest.raises(InvalidAmount):
        Money.from_reais(Decimal("0"))


def test_from_reais_rejects_float_input() -> None:
    with pytest.raises(InvalidAmount):
        Money.from_reais(45.0)  # type: ignore[arg-type]
