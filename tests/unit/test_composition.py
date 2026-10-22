"""Unit tests for the Telegram composition root's spending-search wiring."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from myfinance.config import Settings
from myfinance.infrastructure.parsing.follow_up import OpenCodeFollowUpResolver
from myfinance.infrastructure.parsing.spending_query import (
    DeterministicSpendingQueryParser,
    OpenCodeSpendingQueryParser,
)
from myfinance.infrastructure.sqlite import SqliteConversationMemory
from myfinance.presentation.telegram.composition import build_container


def make_settings(tmp_path: Path, *, opencode_api_key: str | None) -> Settings:
    return Settings(
        _env_file=None,
        pluggy_client_id=uuid4(),
        pluggy_client_secret="secret",
        telegram_owner_id=1,
        database_path=tmp_path / "test.db",
        opencode_api_key=opencode_api_key,
    )


def test_build_container_uses_opencode_parser_when_key_present(
    tmp_path: Path,
) -> None:
    container = build_container(
        make_settings(tmp_path, opencode_api_key="test-key")
    )

    # The container exposes use cases, so observe the parser wiring through
    # the use case that owns it.
    search = container.handle_message._spending_search
    assert search is not None
    assert isinstance(search._parser, OpenCodeSpendingQueryParser)


def test_build_container_uses_deterministic_parser_without_key(
    tmp_path: Path,
) -> None:
    container = build_container(make_settings(tmp_path, opencode_api_key=None))

    search = container.handle_message._spending_search
    assert search is not None
    assert isinstance(search._parser, DeterministicSpendingQueryParser)


def test_build_container_reuses_one_language_model(tmp_path: Path) -> None:
    container = build_container(
        make_settings(tmp_path, opencode_api_key="test-key")
    )

    llm_parser = container.handle_message._parser._fallback
    explain_failure = container.explain_failure
    search = container.handle_message._spending_search
    assert llm_parser is not None
    assert explain_failure is not None
    assert search is not None
    assert llm_parser._model is explain_failure._model
    assert llm_parser._model is search._parser._model


def test_build_container_always_builds_the_conversation_memory(
    tmp_path: Path,
) -> None:
    container = build_container(make_settings(tmp_path, opencode_api_key=None))

    assert isinstance(container.memory, SqliteConversationMemory)


def test_build_container_builds_the_follow_up_resolver_with_a_key(
    tmp_path: Path,
) -> None:
    container = build_container(
        make_settings(tmp_path, opencode_api_key="test-key")
    )

    assert isinstance(container.follow_up, OpenCodeFollowUpResolver)


def test_build_container_without_a_key_has_no_follow_up_resolver(
    tmp_path: Path,
) -> None:
    container = build_container(make_settings(tmp_path, opencode_api_key=None))

    assert container.follow_up is None
