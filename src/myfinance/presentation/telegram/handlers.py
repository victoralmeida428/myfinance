"""Telegram handlers: adapt updates to use cases and render the replies.

Handlers stay thin on purpose: they deduplicate updates, call one use case and
send the rendered text. Conversation state, routing and failure explanations
live in :mod:`myfinance.presentation.telegram.conversation`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from myfinance.application.dto import SummaryMessage
from myfinance.application.errors import (
    ApplicationError,
    InvalidDateReference,
    ProviderError,
)
from myfinance.application.ports import ProcessedUpdateRepository
from myfinance.application.use_cases import (
    GetDayDetailsUseCase,
    GetSummaryUseCase,
    RegisterPluggyItemUseCase,
)
from myfinance.presentation.telegram.commands import HELP_TEXT
from myfinance.presentation.telegram.conversation import TelegramConversation
from myfinance.presentation.telegram.formatting import (
    format_details,
    format_reply,
)

__all__ = ["BotHandlers"]

_INVALID_DATE_REPLY = "Não entendi a data. Use hoje, ontem, amanhã, 2026-10-25 ou 25/10."
_UNSUPPORTED_REPLY = "Por enquanto eu só entendo mensagens de texto."
_INVALID_UUID_REPLY = "UUID inválido."
_ITEM_UNAVAILABLE_REPLY = "Registro de item indisponível."
_ITEM_REGISTERED_REPLY = (
    "Item registrado. Já pode perguntar 'qual meu saldo' ou "
    "'extrato de hoje'."
)

_T = TypeVar("_T")


def _chat_id(update: Update) -> str | None:
    """Return the chat identifier, falling back to the user identifier."""
    chat = getattr(update, "effective_chat", None)
    if chat is not None:
        return str(chat.id)
    user = getattr(update, "effective_user", None)
    if user is not None:
        return str(user.id)
    return None


class BotHandlers:
    """Update handlers backed by the conversation and command use cases."""

    def __init__(
        self,
        *,
        conversation: TelegramConversation,
        summary: GetSummaryUseCase,
        details: GetDayDetailsUseCase,
        updates: ProcessedUpdateRepository,
        register_item: RegisterPluggyItemUseCase | None = None,
    ) -> None:
        self._conversation = conversation
        self._summary = summary
        self._details = details
        self._updates = updates
        self._register_item = register_item

    async def start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Greet the user with the command reference."""
        await self._reply(update, HELP_TEXT)

    async def help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Show the command reference."""
        await self._reply(update, HELP_TEXT)

    async def summary(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Reply with the summary for the requested day or period."""
        reference = self._reference(context.args)
        ok, summary = await self._guarded(
            update,
            self._summary.execute(reference),
            self._question_text(update, "resumo do dia"),
        )
        if not ok:
            return
        assert summary is not None
        await self._reply(update, format_reply(SummaryMessage(summary=summary)))

    async def details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Reply with the entries registered for the requested day."""
        reference = self._reference(context.args)
        ok, details = await self._guarded(
            update,
            self._details.execute(reference),
            self._question_text(update, "detalhes do dia"),
        )
        if not ok:
            return
        assert details is not None
        await self._reply(update, format_details(details.entries, details.day))

    async def message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle a free-form text message, once per Telegram update."""
        if not await self._updates.claim(update.update_id):
            return

        telegram_message = update.effective_message
        if telegram_message is None:
            return
        text = telegram_message.text
        if not text or not text.strip():
            return

        await self._reply(
            update, await self._conversation.respond(_chat_id(update), text)
        )

    async def unsupported(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Politely reject voice/audio messages, which the MVP does not read."""
        await self._reply(update, _UNSUPPORTED_REPLY)

    async def item_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Register a Pluggy item so banking questions can be answered."""
        if self._register_item is None:
            await self._reply(update, _ITEM_UNAVAILABLE_REPLY)
            return

        args = context.args or []
        if not args:
            await self._reply(update, _INVALID_UUID_REPLY)
            return
        try:
            item_uuid = UUID(args[0])
        except ValueError:
            await self._reply(update, _INVALID_UUID_REPLY)
            return

        connector_name = " ".join(args[1:]).strip() or None
        ok, _ = await self._guarded(
            update,
            self._register_item.execute(
                item_uuid, status="created", connector_name=connector_name
            ),
            self._question_text(update, "registrar item do Pluggy"),
            invalid_date=False,
        )
        if ok:
            await self._reply(update, _ITEM_REGISTERED_REPLY)

    async def _guarded(
        self,
        update: Update,
        coro: Awaitable[_T],
        question: str,
        *,
        invalid_date: bool = True,
    ) -> tuple[bool, _T | None]:
        """Await a use case, replying with the right error message on failure."""
        try:
            return True, await coro
        except InvalidDateReference:
            if invalid_date:
                await self._reply(update, _INVALID_DATE_REPLY)
            return False, None
        except (ApplicationError, ProviderError) as exc:
            await self._reply(
                update, await self._conversation.failure_text(question, exc)
            )
            return False, None

    @staticmethod
    def _question_text(update: Update, fallback: str) -> str:
        """Return the command text when present, else a short description."""
        telegram_message = update.effective_message
        text = (
            getattr(telegram_message, "text", None)
            if telegram_message is not None
            else None
        )
        if text and text.strip():
            return text.strip()
        return fallback

    @staticmethod
    def _reference(args: list[str] | None) -> str | None:
        """Join the command arguments into the raw date reference."""
        if not args:
            return None
        return " ".join(args) or None

    @staticmethod
    async def _reply(update: Update, text: str) -> None:
        """Reply to the update's message, tolerating updates without one."""
        telegram_message = update.effective_message
        if telegram_message is None:
            return
        await telegram_message.reply_text(text)
