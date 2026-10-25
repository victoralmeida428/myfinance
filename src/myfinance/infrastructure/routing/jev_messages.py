"""JEV-backed classifier for every message intent.

One System One choice question replaces the old split between the banking
intent router and the summary gate: the model sees the whole sentence and
returns a single label, which the application maps to a routing decision.
"""

from __future__ import annotations

import httpx

from myfinance.application.intents import MessageIntent, RoutingDecision
from myfinance.config import Settings
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.parsing.dates import normalize, strip_edges
from myfinance.infrastructure.typesafe.choice import SystemOneChoiceClient

__all__ = ["JevMessageIntentRouter"]

_QUESTION_ID = "intent"
_QUESTION_INSTRUCTIONS = (
    "Classifique a mensagem do usuário em uma única intenção do assistente "
    "financeiro pessoal. Use 'register' para lançamentos com valor e data."
)

_CRITERIA: dict[str, str] = {
    "banking_accounts": (
        "Saldo, contas conectadas, quanto tenho na conta, no banco ou em caixa."
    ),
    "banking_transactions": (
        "Extrato, transações, movimentações, compras do cartão, o que entrou "
        "ou saiu da conta."
    ),
    "banking_identity": "Dados cadastrais, titular, CPF, nome ou identidade.",
    "spending_search": (
        "Quanto gastei com um estabelecimento, categoria, lugar ou termo, em "
        "um período."
    ),
    "spending_comparison": (
        "Comparação entre dois períodos, como 'isso é mais ou menos do que no "
        "mês passado?' ou 'quanto gastei com uber neste mês comparado ao mês "
        "passado?'."
    ),
    "spending_plan": (
        "Plano de gastos, onde cortar, como economizar ou dicas de economia."
    ),
    "top_month": "Qual mês gastou mais, maior gasto ou ranking de meses.",
    "summary": (
        "Resumo ou balanço de gastos/previsões por dia, semana, mês, ano ou "
        "período."
    ),
    "period_details": (
        "Lista de lançamentos de um período, como 'lançamentos de setembro' "
        "ou 'lançamentos do mês de set/2026'."
    ),
    "register": "Registrar gasto, despesa, compra ou previsão com valor e data.",
    "help": "O que o bot pode fazer, comandos, funcionalidades ou ajuda.",
    "income": "Quanto recebi, ganhei, entrou na conta, salário ou receitas.",
}

_DECISIONS: dict[str, RoutingDecision] = {
    "banking_accounts": RoutingDecision(
        MessageIntent.BANKING, BankingIntent.ACCOUNTS
    ),
    "banking_transactions": RoutingDecision(
        MessageIntent.BANKING, BankingIntent.TRANSACTIONS
    ),
    "banking_identity": RoutingDecision(
        MessageIntent.BANKING, BankingIntent.IDENTITY
    ),
    "spending_search": RoutingDecision(MessageIntent.SPENDING_SEARCH),
    "spending_comparison": RoutingDecision(
        MessageIntent.SPENDING_COMPARISON
    ),
    "spending_plan": RoutingDecision(MessageIntent.SPENDING_PLAN),
    "top_month": RoutingDecision(MessageIntent.TOP_MONTH),
    "summary": RoutingDecision(MessageIntent.SUMMARY),
    "period_details": RoutingDecision(MessageIntent.PERIOD_DETAILS),
    "register": RoutingDecision(MessageIntent.REGISTER),
    "help": RoutingDecision(MessageIntent.HELP),
    "income": RoutingDecision(MessageIntent.INCOME),
}


class JevMessageIntentRouter:
    """Classifies a message through TypeSafe's System One API."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = SystemOneChoiceClient(settings, http_client)

    async def classify(self, text: str) -> RoutingDecision | None:
        """Return the chosen decision, or ``None`` when the model abstains."""
        choice = await self._client.choose(
            state=text,
            question_id=_QUESTION_ID,
            instructions=_QUESTION_INSTRUCTIONS,
            criteria=_CRITERIA,
        )
        if choice is None:
            return None
        return _DECISIONS.get(normalize(strip_edges(choice)))
