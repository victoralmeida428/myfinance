"""Turns elliptical follow-up messages into standalone questions.

The resolver never computes amounts and never stores state: it only uses the
recent conversation to make the latest question understandable on its own.
"""

from __future__ import annotations

from collections.abc import Sequence

from myfinance.application.ports import LanguageModel
from myfinance.domain.models import ChatMessage

__all__ = ["OpenCodeFollowUpResolver"]

_SYSTEM_PROMPT = (
    "Você ajuda a interpretar conversas sobre finanças pessoais em português "
    "do Brasil.\n"
    "Receberá o histórico recente da conversa e a mensagem atual do usuário.\n"
    "Reescreva APENAS a mensagem atual como uma pergunta independente, em "
    "português do Brasil, preservando o assunto, o período, o cartão ou a "
    "conta e a intenção que vêm do contexto.\n"
    "Se a mensagem atual já fizer sentido sozinha ou não for uma continuação, "
    "devolva-a sem alterações.\n"
    "Responda somente com a pergunta reescrita, sem aspas e sem explicações. "
    "Nunca invente valores."
)

_ROLE_LABELS = {"user": "Usuário", "assistant": "Bot"}


class OpenCodeFollowUpResolver:
    """Asks a language model to make a follow-up question standalone."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

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
