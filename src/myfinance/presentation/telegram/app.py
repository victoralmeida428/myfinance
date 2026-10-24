"""Telegram application factory and long-polling entrypoint."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from myfinance.config import Settings, get_settings
from myfinance.presentation.telegram.composition import (
    BotContainer,
    build_container,
)
from myfinance.presentation.telegram.handlers import BotHandlers

__all__ = ["build_telegram_application", "run_bot", "seed_configured_item"]

_LOGGER = logging.getLogger(__name__)

_MISSING_TOKEN_MESSAGE = (
    "Missing TELEGRAM_BOT_TOKEN. Create a bot with @BotFather and set it in "
    "the environment."
)

_MISSING_OWNER_MESSAGE = (
    "Missing TELEGRAM_OWNER_ID. Get your numeric Telegram ID from "
    "@userinfobot and set it in the environment."
)


def build_telegram_application(
    settings: Settings, container: BotContainer
) -> Application:
    """Build the polling application with every handler registered."""
    token = _require_token(settings)
    owner = filters.User(user_id=_require_owner(settings))
    handlers = BotHandlers(
        conversation=container.conversation,
        summary=container.summary,
        details=container.details,
        updates=container.updates,
        register_item=container.register_item,
    )

    application = (
        Application.builder().token(token).concurrent_updates(True).build()
    )
    application.add_handler(
        CommandHandler(["start"], handlers.start, filters=owner)
    )
    application.add_handler(
        CommandHandler(["ajuda", "help"], handlers.help, filters=owner)
    )
    application.add_handler(
        CommandHandler("resumo", handlers.summary, filters=owner)
    )
    application.add_handler(
        CommandHandler("detalhes", handlers.details, filters=owner)
    )
    application.add_handler(
        CommandHandler("item", handlers.item_command, filters=owner)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & owner, handlers.message)
    )
    application.add_handler(
        MessageHandler((filters.VOICE | filters.AUDIO) & owner, handlers.unsupported)
    )
    application.add_error_handler(_log_error)
    return application


def seed_configured_item(settings: Settings, container: BotContainer) -> None:
    """Register the Pluggy item configured in the environment, if any."""
    if settings.pluggy_item_id is None:
        return
    asyncio.run(
        container.register_item.execute(
            settings.pluggy_item_id,
            connector_name=settings.pluggy_connector_name,
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
    _require_owner(settings)
    container = build_container(settings)
    seed_configured_item(settings, container)
    application = build_telegram_application(settings, container)
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


def _require_owner(settings: Settings) -> int:
    """Return the allowed Telegram user ID, refusing an open bot."""
    if settings.telegram_owner_id is None:
        raise RuntimeError(_MISSING_OWNER_MESSAGE)
    return settings.telegram_owner_id


async def _log_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Log only the exception class, so message text and tokens stay private."""
    error = context.error
    if error is None:
        return
    _LOGGER.error("Telegram update failed with %s", type(error).__name__)
