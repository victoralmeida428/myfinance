"""Telegram handlers: adapt updates to use cases and render the replies.

Handlers stay thin on purpose: they hold no SQL, no date parsing and no
provider SDK usage. All business decisions live in the application layer and
all rendering lives in :mod:`myfinance.presentation.telegram.formatting`.
"""

from __future__ import annotations

from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from myfinance.application.dto import (
    NeedsClarification,
    RegisteredMessage,
    SpendingAnswerMessage,
    SummaryMessage,
    TopMonthMessage,
)
from myfinance.application.errors import (
    ApplicationError,
    InvalidDateReference,
    ProviderError,
)
from myfinance.application.ports import ProcessedUpdateRepository
from myfinance.application.use_cases import (
    ExplainFailureUseCase,
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodSummaryUseCase,
    HandleBankingQueryUseCase,
    HandleMessageUseCase,
    RegisterPluggyItemUseCase,
)
from myfinance.domain.summary import PeriodSummary
from myfinance.presentation.telegram.commands import HELP_TEXT
from myfinance.presentation.telegram.formatting import (
    format_banking,
    format_details,
    format_period_summary,
    format_registration,
    format_spending_answer,
    format_summary,
    format_top_month,
)

__all__ = ["BotHandlers"]

_INVALID_DATE_REPLY = "Não entendi a data. Use hoje, ontem, amanhã, 2026-10-25 ou 25/10."
_GENERIC_ERROR_REPLY = "Não consegui concluir agora. Tente novamente."
_UNSUPPORTED_REPLY = "Por enquanto eu só entendo mensagens de texto."
_INVALID_UUID_REPLY = "UUID inválido."
_ITEM_UNAVAILABLE_REPLY = "Registro de item indisponível."
_ITEM_REGISTERED_REPLY = (
    "Item registrado. Já pode perguntar 'qual meu saldo' ou "
    "'extrato de hoje'."
)


class BotHandlers:
    """Update handlers backed by the finance use cases."""

    def __init__(
        self,
        *,
        handle_message: HandleMessageUseCase,
        summary: GetDailySummaryUseCase,
        details: GetDayDetailsUseCase,
        updates: ProcessedUpdateRepository,
        period_summary: GetPeriodSummaryUseCase | None = None,
        banking: HandleBankingQueryUseCase | None = None,
        register_item: RegisterPluggyItemUseCase | None = None,
        explain_failure: ExplainFailureUseCase | None = None,
    ) -> None:
        self._handle_message = handle_message
        self._summary = summary
        self._details = details
        self._updates = updates
        self._period_summary = period_summary
        self._banking = banking
        self._register_item = register_item
        self._explain_failure = explain_failure

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
        try:
            if self._period_summary is not None:
                period = await self._period_summary.execute(reference)
                if period is not None:
                    await self._reply(update, format_period_summary(period))
                    return
            summary = await self._summary.execute(reference)
        except InvalidDateReference:
            await self._reply(update, _INVALID_DATE_REPLY)
            return
        except (ApplicationError, ProviderError) as exc:
            await self._reply_failure(
                update, self._question_text(update, "resumo do dia"), exc
            )
            return
        await self._reply(update, format_summary(summary))

    async def details(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Reply with the entries registered for the requested day."""
        reference = self._reference(context.args)
        try:
            entries = await self._details.execute(reference)
            # The use case returns entries only, so an empty day has no day to
            # render; the summary resolves the same reference without any date
            # parsing happening in the presentation layer.
            day = entries[0].day if entries else (
                await self._summary.execute(reference)
            ).day
        except InvalidDateReference:
            await self._reply(update, _INVALID_DATE_REPLY)
            return
        except (ApplicationError, ProviderError) as exc:
            await self._reply_failure(
                update, self._question_text(update, "detalhes do dia"), exc
            )
            return
        await self._reply(update, format_details(entries, day))

    async def message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Register a free-form text message, once per Telegram update."""
        if not await self._updates.claim(update.update_id):
            return

        telegram_message = update.effective_message
        if telegram_message is None:
            return
        text = telegram_message.text
        if not text or not text.strip():
            return

        if self._banking is not None:
            try:
                answer = await self._banking.execute(text)
            except (ApplicationError, ProviderError) as exc:
                await self._reply_failure(update, text, exc)
                return
            if answer is not None:
                await self._reply(update, format_banking(answer))
                return

        try:
            result = await self._handle_message.execute(text)
        except (ApplicationError, ProviderError) as exc:
            await self._reply_failure(update, text, exc)
            return

        if isinstance(result, RegisteredMessage):
            await self._reply(update, format_registration(result.result))
        elif isinstance(result, SummaryMessage):
            if isinstance(result.summary, PeriodSummary):
                await self._reply(update, format_period_summary(result.summary))
            else:
                await self._reply(update, format_summary(result.summary))
        elif isinstance(result, TopMonthMessage):
            await self._reply(update, format_top_month(result))
        elif isinstance(result, SpendingAnswerMessage):
            await self._reply(update, format_spending_answer(result))
        elif isinstance(result, NeedsClarification):
            await self._reply(update, result.reason)

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
        try:
            await self._register_item.execute(
                item_uuid,
                status="created",
                connector_name=connector_name,
            )
        except (ApplicationError, ProviderError) as exc:
            await self._reply_failure(
                update, self._question_text(update, "registrar item do Pluggy"), exc
            )
            return
        await self._reply(update, _ITEM_REGISTERED_REPLY)

    async def _reply_failure(
        self, update: Update, question: str, error: Exception
    ) -> None:
        """Explain the failure when possible, otherwise use the generic reply."""
        if self._explain_failure is None:
            await self._reply(update, _GENERIC_ERROR_REPLY)
            return
        try:
            explanation = await self._explain_failure.execute(
                question=question, error=error
            )
        except ProviderError:
            await self._reply(update, _GENERIC_ERROR_REPLY)
            return
        text = explanation.strip()
        await self._reply(update, text or _GENERIC_ERROR_REPLY)

    @staticmethod
    def _question_text(update: Update, fallback: str) -> str:
        """Return the command text when present, else a short description."""
        telegram_message = update.effective_message
        text = telegram_message.text if telegram_message is not None else None
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
