"""Unit tests for the Telegram composition root's public wiring."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from myfinance.application.use_cases import (
    GetDayDetailsUseCase,
    GetSummaryUseCase,
    RegisterPluggyItemUseCase,
)
from myfinance.config import Settings
from myfinance.infrastructure.parsing.follow_up import OpenCodeFollowUpResolver
from myfinance.infrastructure.parsing.spending_query import (
    DeterministicSpendingQueryParser,
    OpenCodeSpendingQueryParser,
)
from myfinance.infrastructure.sqlite import SqliteProcessedUpdateRepository
from myfinance.presentation.telegram.composition import (
    build_container,
    build_follow_up_resolver,
    build_spending_parser,
)
from myfinance.presentation.telegram.conversation import TelegramConversation


class FakeModel:
    async def complete(self, messages, *, session_id=None) -> str:
        return "ok"


def make_settings(tmp_path: Path, *, opencode_api_key: str | None) -> Settings:
    return Settings(
        _env_file=None,
        pluggy_client_id=uuid4(),
        pluggy_client_secret="secret",
        telegram_owner_id=1,
        database_path=tmp_path / "test.db",
        opencode_api_key=opencode_api_key,
    )


def test_build_spending_parser_uses_opencode_with_a_key(tmp_path: Path) -> None:
    parser = build_spending_parser(
        make_settings(tmp_path, opencode_api_key="test-key"), FakeModel()
    )

    assert isinstance(parser, OpenCodeSpendingQueryParser)


def test_build_spending_parser_falls_back_without_a_key(tmp_path: Path) -> None:
    parser = build_spending_parser(
        make_settings(tmp_path, opencode_api_key=None), None
    )

    assert isinstance(parser, DeterministicSpendingQueryParser)


def test_build_follow_up_resolver_requires_both_key_and_model(
    tmp_path: Path,
) -> None:
    with_key = make_settings(tmp_path, opencode_api_key="test-key")
    without_key = make_settings(tmp_path, opencode_api_key=None)

    assert isinstance(
        build_follow_up_resolver(with_key, FakeModel()),
        OpenCodeFollowUpResolver,
    )
    assert build_follow_up_resolver(without_key, FakeModel()) is None
    assert build_follow_up_resolver(with_key, None) is None


def test_build_container_wires_the_jev_classifier(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        pluggy_client_id=uuid4(),
        pluggy_client_secret="secret",
        telegram_owner_id=1,
        database_path=tmp_path / "test.db",
        categorizer_api_token="test-token",
    )

    container = build_container(settings)

    assert isinstance(container.conversation, TelegramConversation)


def test_build_container_exposes_only_the_handler_entry_points(
    tmp_path: Path,
) -> None:
    for key in (None, "test-key"):
        container = build_container(
            make_settings(tmp_path, opencode_api_key=key)
        )

        assert isinstance(container.conversation, TelegramConversation)
        assert isinstance(container.summary, GetSummaryUseCase)
        assert isinstance(container.details, GetDayDetailsUseCase)
        assert isinstance(container.updates, SqliteProcessedUpdateRepository)
        assert isinstance(container.register_item, RegisterPluggyItemUseCase)
