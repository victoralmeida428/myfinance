"""Expense categories known to the finance bot."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Category"]


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
