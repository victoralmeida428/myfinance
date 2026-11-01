"""Unit tests for per-account Telegram routing and access restriction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.ext import Application, MessageHandler

from myfinance.accounts import AccountProfile
from myfinance.config import Settings
from myfinance.presentation.telegram.app import build_telegram_application
from myfinance.presentation.telegram.composition import BotAccount
from myfinance.presentation.telegram.handlers import BotHandlers


def make_container() -> SimpleNamespace:
    """A container whose use cases are never invoked by these tests."""
    return SimpleNamespace(
        conversation=None,
        summary=None,
        details=None,
        updates=None,
        register_item=None,
    )


def make_account(user_id: int) -> BotAccount:
    return BotAccount(
        profile=AccountProfile(
            id=f"user-{user_id}",
            name=f"User {user_id}",
            telegram_user_id=user_id,
            settings=Settings(
                _env_file=None,
                telegram_owner_id=user_id,
            ),
        ),
        container=make_container(),  # type: ignore[arg-type]
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


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="123:abc",
    )


def test_build_fails_without_accounts() -> None:
    with pytest.raises(RuntimeError, match="No accounts configured"):
        build_telegram_application(make_settings(), [])


def test_build_registers_seven_handlers_per_account() -> None:
    application = build_telegram_application(
        make_settings(), [make_account(42), make_account(43)]
    )

    total = sum(len(group) for group in application.handlers.values())
    assert total == 14
    assert isinstance(application, Application)
    assert set(application.handlers) == {0, 1}


def test_each_account_only_accepts_its_own_user() -> None:
    application = build_telegram_application(
        make_settings(), [make_account(42), make_account(43)]
    )

    first_group = [
        handler
        for handler in application.handlers[0]
        if isinstance(handler, MessageHandler)
        and handler.callback.__name__ == "message"
    ]
    second_group = [
        handler
        for handler in application.handlers[1]
        if isinstance(handler, MessageHandler)
        and handler.callback.__name__ == "message"
    ]
    assert len(first_group) == 1
    assert len(second_group) == 1

    assert first_group[0].filters.check_update(make_update(42)) is True
    assert first_group[0].filters.check_update(make_update(43)) is False
    assert second_group[0].filters.check_update(make_update(43)) is True
    assert second_group[0].filters.check_update(make_update(42)) is False
    assert second_group[0].filters.check_update(make_update(99)) is False


def test_command_handlers_reject_other_users() -> None:
    application = build_telegram_application(
        make_settings(), [make_account(42), make_account(43)]
    )

    for group, own_user, other_user in ((0, 42, 43), (1, 43, 42)):
        command_handlers = [
            handler
            for handler in application.handlers[group]
            if hasattr(handler, "commands")
        ]
        assert len(command_handlers) == 5
        for handler in command_handlers:
            assert handler.filters.check_update(make_update(own_user)) is True
            assert handler.filters.check_update(make_update(other_user)) is False


def test_handlers_are_wired_to_the_bot_handlers() -> None:
    application = build_telegram_application(
        make_settings(), [make_account(42), make_account(43)]
    )

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
