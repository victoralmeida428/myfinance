"""Telegram conversation flow: history, follow-up, dispatch and rendering."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from myfinance.application.errors import ApplicationError, ProviderError
from myfinance.application.ports import ConversationMemory, FollowUpResolver
from myfinance.application.use_cases import (
    ExplainFailureUseCase,
    HandleConversationMessageUseCase,
)
from myfinance.domain.models import ChatMessage
from myfinance.presentation.telegram.formatting import format_reply

__all__ = ["TelegramConversation"]

_LOGGER = logging.getLogger(__name__)

_GENERIC_ERROR_REPLY = "Não consegui concluir agora. Tente novamente."


class TelegramConversation:
    """Owns the stateful part of a Telegram message flow."""

    def __init__(
        self,
        *,
        incoming: HandleConversationMessageUseCase,
        memory: ConversationMemory | None = None,
        follow_up: FollowUpResolver | None = None,
        explain_failure: ExplainFailureUseCase | None = None,
    ) -> None:
        self._incoming = incoming
        self._memory = memory
        self._follow_up = follow_up
        self._explain_failure = explain_failure

    async def respond(self, chat_id: str | None, text: str) -> str:
        """Answer a message, explaining provider failures in plain Portuguese."""
        try:
            return await self._respond(chat_id, text)
        except (ApplicationError, ProviderError) as exc:
            return await self.failure_text(text, exc)

    async def failure_text(self, question: str, error: Exception) -> str:
        """Explain a failure, falling back to a static reply when unavailable."""
        if self._explain_failure is None:
            return _GENERIC_ERROR_REPLY
        try:
            explanation = await self._explain_failure.execute(
                question=question, error=error
            )
        except ProviderError:
            return _GENERIC_ERROR_REPLY
        return explanation.strip() or _GENERIC_ERROR_REPLY

    async def _respond(self, chat_id: str | None, text: str) -> str:
        original_text = text
        history = await self._history(chat_id)
        if (
            history
            and self._follow_up is not None
            and self._follow_up.should_rewrite(text)
        ):
            try:
                rewritten = await self._follow_up.rewrite(text, history)
            except ProviderError:
                rewritten = None
            if rewritten:
                text = rewritten

        await self._remember(chat_id, "user", original_text)
        reply = await self._incoming.execute(text)
        rendered = format_reply(reply)
        await self._remember(chat_id, "assistant", rendered)
        return rendered

    async def _history(self, chat_id: str | None) -> Sequence[ChatMessage]:
        """Load recent exchanges, tolerating an unavailable memory."""
        if self._memory is None or chat_id is None:
            return ()
        try:
            return await self._memory.recent(chat_id, exchanges=5)
        except Exception as exc:
            _LOGGER.error(
                "Conversation memory read failed with %s", type(exc).__name__
            )
            return ()

    async def _remember(
        self,
        chat_id: str | None,
        role: Literal["user", "assistant"],
        content: str,
    ) -> None:
        """Store a message without ever breaking the reply on failure."""
        if self._memory is None or chat_id is None:
            return
        try:
            await self._memory.append(chat_id, role, content)
        except Exception as exc:
            _LOGGER.error(
                "Conversation memory write failed with %s", type(exc).__name__
            )
