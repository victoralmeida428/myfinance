"""Deterministic banking intent routing by keyword.

Strong phrases decide the intent offline. Ambiguous banking words return
``None`` so a composite router can hand the sentence to a smarter classifier
instead of guessing.
"""

from __future__ import annotations

from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.parsing.dates import normalize


def _phrases(*words: str) -> tuple[str, ...]:
    return tuple(normalize(word) for word in words)


_STRONG_INTENTS: tuple[tuple[BankingIntent, tuple[str, ...]], ...] = (
    (
        BankingIntent.ACCOUNTS,
        _phrases(
            "saldo",
            "contas",
            "quanto tenho",
            "conta corrente",
            "contas conectadas",
        ),
    ),
    (
        BankingIntent.TRANSACTIONS,
        _phrases(
            "extrato",
            "transacoes",
            "transações",
            "movimentacoes",
            "movimentações",
            "compras",
            "o que entrou",
            "o que saiu",
        ),
    ),
    (
        BankingIntent.IDENTITY,
        _phrases(
            "meus dados",
            "titular",
            "cpf",
            "identidade",
            "cadastro",
        ),
    ),
)

_BANKING_HINTS = frozenset(
    _phrases(
        "banco",
        "conta",
        "cartao",
        "cartão",
        "pluggy",
        "saldo",
        "extrato",
        "transacao",
        "transação",
        "dados",
        "cpf",
    )
)


class KeywordIntentRouter:
    """Routes banking questions using a deterministic keyword map."""

    async def route(self, text: str) -> BankingIntent | None:
        """Return the intent, ``None`` for an ambiguous banking hint, or NONE.

        ``None`` means "this looks like banking, but the intent is unclear";
        :class:`CompositeIntentRouter` uses it to decide whether to ask Jev.
        """
        normalized = normalize(text)

        for intent, phrases in _STRONG_INTENTS:
            if any(phrase in normalized for phrase in phrases):
                return intent

        if any(hint in normalized for hint in _BANKING_HINTS):
            return None

        return BankingIntent.NONE
