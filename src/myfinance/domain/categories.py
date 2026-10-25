"""Expense categories known to the finance bot."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Category", "coerce_category"]


class Category(StrEnum):
    """The category a financial entry belongs to."""

    ALIMENTACAO = "alimentacao"
    TRANSPORTE = "transporte"
    LAZER = "lazer"
    SAUDE = "saude"
    SERVICOS = "servicos"
    OUTROS = "outros"

    @property
    def label(self) -> str:
        """Return the human-readable label shown to users."""
        return _LABELS[self]


_LABELS: dict[Category, str] = {
    Category.ALIMENTACAO: "Alimentação",
    Category.TRANSPORTE: "Transporte",
    Category.LAZER: "Lazer",
    Category.SAUDE: "Saúde",
    Category.SERVICOS: "Serviços",
    Category.OUTROS: "Outros",
}


def coerce_category(value: object) -> Category:
    """Return a valid category, falling back to ``OUTROS`` for bad input."""
    if isinstance(value, Category):
        return value
    if isinstance(value, str):
        try:
            return Category(value)
        except ValueError:
            pass
    return Category.OUTROS
