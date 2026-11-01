"""Unit tests for the Telegram composition root's public wiring."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from myfinance.accounts import AccountProfile
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
    build_bot_accounts,
    build_container,
    build_follow_up_resolver,
    build_spending_parser,
)
from myfinance.presentation.telegram.conversation import TelegramConversation


class FakeModel:
    async def complete(self, messages, *, session_id=None) -> str:
        return "ok"


def make_settings(
    tmp_path: Path,
    *,
    opencode_api_key: str | None,
    categorizer_api_token: str | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        pluggy_client_id=uuid4(),
        pluggy_client_secret="secret",
        telegram_owner_id=1,
        database_path=tmp_path / "test.db",
        opencode_api_key=opencode_api_key,
        categorizer_api_token=categorizer_api_token,
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


def capture_bank_expense_classifier(
    monkeypatch, settings: Settings
) -> dict[str, object]:
    from myfinance.presentation.telegram import composition

    captured: dict[str, object] = {}

    class CapturingProvider(composition.PluggyBankExpenseProvider):
        def __init__(self, banking, items, classifier):
            captured["classifier"] = classifier
            super().__init__(banking, items, classifier)

    monkeypatch.setattr(
        composition, "PluggyBankExpenseProvider", CapturingProvider
    )
    composition.build_container(settings)
    return captured


def test_build_container_uses_the_category_classifier_for_bank_expenses(
    tmp_path: Path, monkeypatch
) -> None:
    from myfinance.infrastructure.categorization import (
        FallbackCategoryClassifier,
    )

    settings = make_settings(
        tmp_path,
        opencode_api_key=None,
        categorizer_api_token="test-token",
    )
    captured = capture_bank_expense_classifier(monkeypatch, settings)

    assert isinstance(captured["classifier"], FallbackCategoryClassifier)


def test_build_container_gives_bank_expenses_a_classifier_without_a_token(
    tmp_path: Path, monkeypatch
) -> None:
    from myfinance.infrastructure.categorization import (
        KeywordCategoryClassifier,
    )

    settings = make_settings(tmp_path, opencode_api_key=None)
    captured = capture_bank_expense_classifier(monkeypatch, settings)

    assert isinstance(captured["classifier"], KeywordCategoryClassifier)


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


def test_build_bot_accounts_creates_one_database_per_account(
    tmp_path: Path,
) -> None:
    profiles = tuple(
        AccountProfile(
            id=f"account-{index}",
            name=f"Account {index}",
            telegram_user_id=index,
            settings=make_settings(
                tmp_path, opencode_api_key=None
            ).model_copy(
                update={"database_path": tmp_path / f"account-{index}.db"}
            ),
        )
        for index in (1, 2)
    )

    accounts = build_bot_accounts(profiles)

    assert [account.profile.id for account in accounts] == [
        "account-1",
        "account-2",
    ]
    assert (tmp_path / "account-1.db").exists()
    assert (tmp_path / "account-2.db").exists()
    assert accounts[0].container is not accounts[1].container
