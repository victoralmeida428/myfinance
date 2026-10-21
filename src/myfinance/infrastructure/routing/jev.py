"""Jev-backed banking intent router.

Only used for sentences that mention banking but whose intent the keyword
router cannot decide. The model's raw choice is mapped back to the domain
enum and anything unknown degrades to ``BankingIntent.NONE``.
"""

from __future__ import annotations

import httpx

from myfinance.config import Settings
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.parsing.dates import normalize, strip_edges
from myfinance.infrastructure.typesafe.choice import SystemOneChoiceClient

_QUESTION_ID = "intent"
_QUESTION_INSTRUCTIONS = (
    "Classifique o pedido do usuário sobre a conta bancária conectada. "
    "Se não for sobre a conta bancária, escolha none."
)

_CRITERIA: dict[str, str] = {
    "accounts": "Saldo, contas, quanto tenho no banco, contas conectadas.",
    "transactions": (
        "Extrato, transações, movimentações, compras do cartão, "
        "o que entrou ou saiu."
    ),
    "identity": "Dados cadastrais, titular, CPF, nome, identidade.",
    "none": (
        "Registrar gasto ou previsão, resumo de orçamento, categorias, "
        "ajuda, ou qualquer outro assunto."
    ),
}

_INTENTS: dict[str, BankingIntent] = {
    "accounts": BankingIntent.ACCOUNTS,
    "transactions": BankingIntent.TRANSACTIONS,
    "identity": BankingIntent.IDENTITY,
    "none": BankingIntent.NONE,
}


class JevIntentRouter:
    """Classifies ambiguous banking sentences through TypeSafe's API."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = SystemOneChoiceClient(settings, http_client)

    async def route(self, text: str) -> BankingIntent:
        choice = await self._client.choose(
            state=text,
            question_id=_QUESTION_ID,
            instructions=_QUESTION_INSTRUCTIONS,
            criteria=_CRITERIA,
        )
        if choice is None:
            return BankingIntent.NONE
        return _INTENTS.get(normalize(strip_edges(choice)), BankingIntent.NONE)
