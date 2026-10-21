"""Monetary amounts, always stored as integer cents."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from myfinance.domain.exceptions import InvalidAmount

__all__ = ["Money"]

_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    """A positive monetary amount expressed in whole cents."""

    cents: int

    def __post_init__(self) -> None:
        if isinstance(self.cents, bool) or not isinstance(self.cents, int):
            raise InvalidAmount("cents must be an int.")
        if self.cents <= 0:
            raise InvalidAmount("cents must be greater than zero.")

    @classmethod
    def from_reais(cls, amount: Decimal) -> Money:
        """Build a ``Money`` from a reais amount, rounding half up to cents."""
        if not isinstance(amount, Decimal):
            raise InvalidAmount("amount must be a Decimal.")
        quantized = amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        return cls(int(quantized * 100))
