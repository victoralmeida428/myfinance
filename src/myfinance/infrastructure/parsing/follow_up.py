"""Turns elliptical follow-up messages into standalone questions.

The resolver never computes amounts and never stores state: it only uses the
recent conversation to make the latest question understandable on its own.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from myfinance.application.ports import LanguageModel
from myfinance.domain.models import ChatMessage
from myfinance.infrastructure.parsing.amounts import find_amount

__all__ = ["OpenCodeFollowUpResolver", "looks_like_follow_up"]

_SYSTEM_PROMPT = (
    "Você ajuda a interpretar conversas sobre finanças pessoais em português "
    "do Brasil.\n"
    "Receberá o histórico recente da conversa e a mensagem atual do usuário.\n"
    "Reescreva APENAS a mensagem atual como uma pergunta independente, em "
    "português do Brasil, preservando o assunto, o período, o cartão ou a "
    "conta e a intenção que vêm do contexto.\n"
    "Se a mensagem atual comparar a resposta anterior com outro período "
    "(por exemplo, \"isso é mais ou menos do que no mês passado?\"), "
    "reescreva-a como uma pergunta de comparação, preservando o assunto e os "
    "dois períodos. Exemplo: \"quanto gastei com uber neste mês comparado ao "
    "mês passado?\".\n"
    "Se a mensagem atual já fizer sentido sozinha ou não for uma continuação, "
    "devolva-a sem alterações.\n"
    "Responda somente com a pergunta reescrita, sem aspas e sem explicações. "
    "Nunca invente valores."
)

_ROLE_LABELS = {"user": "Usuário", "assistant": "Bot"}

_FOLLOW_UP_PREFIXES = (
    "e ",
    "e,",
    "tambem",
    "agora",
    "no cartao",
    "na conta",
    "desse",
    "mesmo",
    "e de",
    "e em",
    "e no",
    "e na",
    "isso ",
    "esse valor",
    "esse total",
    "essa quantia",
    "comparado",
    "em comparacao",
    "em relacao",
    "mais ou menos",
    "foi mais",
    "foi menos",
    "do que no mes",
    "do que mes",
    "vs ",
    "versus",
)

_STANDALONE_STARTERS = (
    "resumo",
    "resume",
    "balanco",
    "saldo",
    "extrato",
    "transacao",
    "transacoes",
    "conta",
    "cartao",
    "fatura",
    "ajuda",
    "help",
    "comando",
    "comandos",
    "quanto",
    "qual",
    "quais",
    "onde",
    "como",
    "detalhes",
    "dados",
    "titular",
    "cpf",
    "plano",
    "planejamento",
    "gastei",
    "gastos",
    "gasto",
    "me ajuda",
    "me mostra",
    "pode me ajudar",
    "quero",
)

_STANDALONE_CONTAINS = (
    "resumo",
    "resume",
    "balanco",
    "saldo",
    "extrato",
    "transacao",
    "transacoes",
    "ajuda",
    "help",
    "comando",
    "comandos",
    "plano",
    "planejamento",
    "detalhes",
    "dados",
    "titular",
    "cpf",
    "gastos",
    "gasto",
    "gastei",
    "fatura",
    "funcionalidades",
    "funcoes",
    "cortar",
    "economizar",
)

_MAX_FOLLOW_UP_WORDS = 3

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_SPAN_RE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _has_explicit_amount(text: str) -> bool:
    """Return whether ``text`` carries a money-like amount outside dates."""
    masked = _ISO_DATE_RE.sub(" ", text)
    masked = _DATE_SPAN_RE.sub(" ", masked)
    masked = _YEAR_RE.sub(" ", masked)
    return find_amount(masked) is not None


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def looks_like_follow_up(text: str) -> bool:
    """Return whether ``text`` is elliptical enough to need conversation context.

    Complete requests such as "Resumo da semana" or "qual meu saldo" must not
    be rewritten: doing so can change their intent based on the previous
    message. Only short fragments that do not carry a standalone intent marker
    are considered.
    """
    normalized = _normalize(text)
    if not normalized:
        return False

    words = normalized.split()
    if any(marker in normalized for marker in _STANDALONE_CONTAINS):
        return False
    if normalized.startswith(_STANDALONE_STARTERS):
        return False
    if _has_explicit_amount(text):
        return False
    if normalized.startswith(_FOLLOW_UP_PREFIXES):
        return True
    if all(word.isdigit() for word in words):
        return False
    return len(words) <= _MAX_FOLLOW_UP_WORDS


class OpenCodeFollowUpResolver:
    """Asks a language model to make a follow-up question standalone."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    def should_rewrite(self, text: str) -> bool:
        return looks_like_follow_up(text)

    async def rewrite(
        self, text: str, history: Sequence[ChatMessage]
    ) -> str | None:
        stripped = text.strip()
        if not stripped:
            return None
        if not history:
            return stripped
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=_user_prompt(stripped, history)),
        ]
        raw = await self._model.complete(messages)
        return raw.strip() or None


def _user_prompt(text: str, history: Sequence[ChatMessage]) -> str:
    lines = [
        f"{_ROLE_LABELS.get(message.role, message.role)}: {message.content}"
        for message in history
    ]
    lines.append(f"Mensagem atual: {text}")
    return "\n".join(lines)
