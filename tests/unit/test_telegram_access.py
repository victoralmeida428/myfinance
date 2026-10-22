"""Unit tests for the Telegram owner-only access restriction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.ext import Application, MessageHandler

from myfinance.config import Settings
from myfinance.presentation.telegram.app import build_telegram_application
from myfinance.presentation.telegram.handlers import BotHandlers


def make_container() -> SimpleNamespace:
    """A container whose use cases are never invoked by these tests."""
    return SimpleNamespace(
        handle_message=None,
        summary=None,
        details=None,
        updates=None,
        period_summary=None,
        banking=None,
        register_item=None,
        explain_failure=None,
        memory=None,
        follow_up=None,
    )


def make_update(user_id: int) -> Update:
    update = Update.de_json(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "User",
                },
                "text": "qual meu saldo",
            },
        }
    )
    assert update is not None
    return update


def make_settings(owner_id: int | None) -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="123:abc",
        telegram_owner_id=owner_id,
    )


@pytest.fixture(autouse=True)
def _clear_owner_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_OWNER_ID", raising=False)


def test_build_fails_without_an_owner() -> None:
    with pytest.raises(RuntimeError, match="TELEGRAM_OWNER_ID"):
        build_telegram_application(make_settings(None), make_container())


def test_build_registers_exactly_seven_handlers() -> None:
    application = build_telegram_application(make_settings(42), make_container())

    total = sum(len(group) for group in application.handlers.values())
    assert total == 7
    assert isinstance(application, Application)


def test_only_the_owner_user_id_passes_the_text_handler() -> None:
    application = build_telegram_application(make_settings(42), make_container())

    text_handlers = [
        handler
        for group in application.handlers.values()
        for handler in group
        if isinstance(handler, MessageHandler)
        and handler.callback.__name__ == "message"
    ]
    assert len(text_handlers) == 1
    text_filter = text_handlers[0].filters

    assert text_filter.check_update(make_update(42)) is True
    assert text_filter.check_update(make_update(43)) is False


def test_command_handlers_reject_other_users() -> None:
    application = build_telegram_application(make_settings(42), make_container())

    command_handlers = [
        handler
        for group in application.handlers.values()
        for handler in group
        if hasattr(handler, "commands")
    ]
    assert len(command_handlers) == 5
    for handler in command_handlers:
        assert handler.filters.check_update(make_update(42)) is True
        assert handler.filters.check_update(make_update(43)) is False


def test_handlers_are_wired_to_the_bot_handlers() -> None:
    application = build_telegram_application(make_settings(42), make_container())

    callbacks = {
        handler.callback.__name__
        for group in application.handlers.values()
        for handler in group
    }
    assert callbacks == {
        "start",
        "help",
        "summary",
        "details",
        "item_command",
        "message",
        "unsupported",
    }
    assert all(
        isinstance(handler.callback.__self__, BotHandlers)
        for group in application.handlers.values()
        for handler in group
    )
