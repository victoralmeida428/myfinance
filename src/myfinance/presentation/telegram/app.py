"""Telegram application factory and long-polling entrypoint."""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Sequence
from uuid import UUID

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from myfinance.accounts import load_accounts
from myfinance.config import Settings, get_settings
from myfinance.presentation.telegram.composition import (
    BotAccount,
    BotContainer,
    build_bot_accounts,
)
from myfinance.presentation.telegram.handlers import BotHandlers

__all__ = [
    "build_telegram_application",
    "run_bot",
    "seed_configured_item",
    "seed_configured_items",
]

_LOGGER = logging.getLogger(__name__)

_MISSING_TOKEN_MESSAGE = (
    "Missing TELEGRAM_BOT_TOKEN. Create a bot with @BotFather and set it in "
    "the environment."
)

_MISSING_ACCOUNTS_MESSAGE = (
    "No accounts configured. Create accounts.toml from accounts.example.toml "
    "and keep it secret."
)


def build_telegram_application(
    settings: Settings, accounts: Sequence[BotAccount]
) -> Application:
    """Build the polling application with one handler group per account."""
    token = _require_token(settings)
    if not accounts:
        raise RuntimeError(_MISSING_ACCOUNTS_MESSAGE)

    application = (
        Application.builder().token(token).concurrent_updates(True).build()
    )
    for group, account in enumerate(accounts):
        owner = filters.User(user_id=account.profile.telegram_user_id)
        handlers = BotHandlers(
            conversation=account.container.conversation,
            summary=account.container.summary,
            details=account.container.details,
            updates=account.container.updates,
            register_item=account.container.register_item,
        )
        application.add_handler(
            CommandHandler(["start"], handlers.start, filters=owner),
            group=group,
        )
        application.add_handler(
            CommandHandler(["ajuda", "help"], handlers.help, filters=owner),
            group=group,
        )
        application.add_handler(
            CommandHandler("resumo", handlers.summary, filters=owner),
            group=group,
        )
        application.add_handler(
            CommandHandler("detalhes", handlers.details, filters=owner),
            group=group,
        )
        application.add_handler(
            CommandHandler("item", handlers.item_command, filters=owner),
            group=group,
        )
        application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & owner, handlers.message
            ),
            group=group,
        )
        application.add_handler(
            MessageHandler(
                (filters.VOICE | filters.AUDIO) & owner, handlers.unsupported
            ),
            group=group,
        )

    application.add_error_handler(_log_error)
    return application


def seed_configured_item(settings: Settings, container: BotContainer) -> None:
    """Register the single Pluggy item configured in the environment, if any."""
    if settings.pluggy_item_id is None:
        return
    _register_pluggy_item(
        container, settings.pluggy_item_id, settings.pluggy_connector_name
    )


def seed_configured_items(accounts: Sequence[BotAccount]) -> None:
    """Register every configured Pluggy item for every account."""
    for account in accounts:
        for item in account.profile.pluggy_items:
            _register_pluggy_item(
                account.container, item.item_id, item.connector_name
            )


def _register_pluggy_item(
    container: BotContainer,
    item_id: UUID,
    connector_name: str | None,
) -> None:
    asyncio.run(
        container.register_item.execute(
            item_id,
            connector_name=connector_name,
        )
    )


def _configure_logging() -> None:
    """Configure app logging without leaking request URLs (and bot tokens)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for name in ("httpx", "httpcore", "httpx2", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def run_bot() -> None:
    """Start the bot in long-polling mode (no HTTP server is exposed)."""
    _configure_logging()
    settings = get_settings()
    _require_token(settings)
    accounts = build_bot_accounts(load_accounts(settings))
    seed_configured_items(accounts)
    application = build_telegram_application(settings, accounts)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


def _require_token(settings: Settings) -> str:
    """Return the bot token, refusing to start when it is missing."""
    secret = settings.telegram_bot_token
    if secret is None:
        raise RuntimeError(_MISSING_TOKEN_MESSAGE)
    token = secret.get_secret_value().strip()
    if not token:
        raise RuntimeError(_MISSING_TOKEN_MESSAGE)
    return token


async def _log_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Log the exception class and frame locations, never message text."""
    error = context.error
    if error is None:
        return
    _LOGGER.error("Telegram update failed with %s", type(error).__name__)
    if isinstance(error, AttributeError):
        # AttributeError messages name the missing attribute; they do not
        # contain user text, tokens or provider payloads.
        _LOGGER.error("  detail: %s", error)
    for frame in traceback.extract_tb(error.__traceback__)[-4:]:
        _LOGGER.error(
            "  at %s:%s in %s", frame.filename, frame.lineno, frame.name
        )
