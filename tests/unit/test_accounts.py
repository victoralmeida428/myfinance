"""Unit tests for loading the secret per-account configuration."""

from __future__ import annotations

import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

from myfinance.accounts import AccountPluggyItem, load_accounts
from myfinance.config import Settings


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the repository's real .env out of the loader tests."""
    monkeypatch.chdir(tmp_path)


def make_settings(tmp_path: Path, *, file_name: str = "accounts.toml") -> Settings:
    return Settings(
        _env_file=None,
        accounts_file=tmp_path / file_name,
        telegram_bot_token="123:abc",
        opencode_api_key="shared-key",
        timezone="America/Sao_Paulo",
    )


def write_accounts(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_loads_accounts_with_their_own_database_and_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = uuid4()
    first_item = uuid4()
    second_item = uuid4()
    maria_item = uuid4()
    monkeypatch.setenv("PLUGGY_CLIENT_ID", str(client_id))
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "global-secret")
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", str(uuid4()))
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "maria-secret")

    write_accounts(
        tmp_path / "accounts.toml",
        f"""
        [[accounts]]
        id = "victor"
        name = "Victor"
        telegram_user_id = 42
        database_path = "data/victor.db"
        pluggy_client_id_env = "PLUGGY_CLIENT_ID"
        pluggy_client_secret_env = "PLUGGY_CLIENT_SECRET"
        pluggy_items = [
            {{ item_id = "{first_item}", connector_name = "Banco A" }},
            {{ item_id = "{second_item}" }},
        ]

        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "data/maria.db"
        pluggy_item_id = "{maria_item}"
        pluggy_connector_name = "Banco B"
        """,
    )

    victor, maria = load_accounts(make_settings(tmp_path))

    assert victor.id == "victor"
    assert victor.name == "Victor"
    assert victor.telegram_user_id == 42
    assert victor.settings.database_path == (tmp_path / "data/victor.db").resolve()
    assert victor.settings.pluggy_client_id == client_id
    assert victor.settings.pluggy_connector_name == "Banco A"
    assert victor.pluggy_items == (
        AccountPluggyItem(item_id=first_item, connector_name="Banco A"),
        AccountPluggyItem(item_id=second_item),
    )
    assert victor.settings.opencode_api_key is not None
    assert victor.settings.opencode_api_key.get_secret_value() == "shared-key"
    assert victor.settings.telegram_bot_token is not None
    assert victor.settings.telegram_bot_token.get_secret_value() == "123:abc"
    assert victor.settings.timezone == "America/Sao_Paulo"

    assert maria.name == "maria"
    assert maria.telegram_user_id == 43
    assert maria.settings.database_path == (tmp_path / "data/maria.db").resolve()
    assert maria.settings.pluggy_client_secret is not None
    assert (
        maria.settings.pluggy_client_secret.get_secret_value() == "maria-secret"
    )
    assert maria.pluggy_items == (
        AccountPluggyItem(item_id=maria_item, connector_name="Banco B"),
    )


def test_reads_credentials_from_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", raising=False)
    monkeypatch.delenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", raising=False)
    client_id = uuid4()
    (tmp_path / ".env").write_text(
        "ACCOUNT_MARIA_PLUGGY_CLIENT_ID="
        f"{client_id}\n"
        "ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET=from-dotenv\n",
        encoding="utf-8",
    )
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        """,
    )

    (profile,) = load_accounts(make_settings(tmp_path))

    assert profile.settings.pluggy_client_id == client_id
    assert profile.settings.pluggy_client_secret is not None
    assert (
        profile.settings.pluggy_client_secret.get_secret_value()
        == "from-dotenv"
    )


def test_missing_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Missing"):
        load_accounts(make_settings(tmp_path))


def test_directory_instead_of_file_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / "accounts.toml").mkdir()

    with pytest.raises(RuntimeError, match="regular file"):
        load_accounts(make_settings(tmp_path))


def test_invalid_toml_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "accounts.toml").write_text("not = [", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid TOML"):
        load_accounts(make_settings(tmp_path))


def test_unknown_field_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", str(uuid4()))
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        unknown = "typo"
        """,
    )

    with pytest.raises(RuntimeError, match="Invalid account configuration"):
        load_accounts(make_settings(tmp_path))


def test_rejects_mixing_pluggy_item_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", str(uuid4()))
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        f"""
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        pluggy_item_id = "{uuid4()}"
        pluggy_items = [
            {{ item_id = "{uuid4()}" }},
        ]
        """,
    )

    with pytest.raises(RuntimeError, match="not both"):
        load_accounts(make_settings(tmp_path))


def test_duplicate_pluggy_item_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", str(uuid4()))
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "secret")
    item_id = uuid4()
    write_accounts(
        tmp_path / "accounts.toml",
        f"""
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        pluggy_items = [
            {{ item_id = "{item_id}" }},
            {{ item_id = "{item_id}" }},
        ]
        """,
    )

    with pytest.raises(RuntimeError, match="duplicate pluggy_item_id"):
        load_accounts(make_settings(tmp_path))


def test_missing_credentials_name_the_account_and_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", raising=False)
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        """,
    )

    with pytest.raises(
        RuntimeError, match="ACCOUNT_MARIA_PLUGGY_CLIENT_ID"
    ):
        load_accounts(make_settings(tmp_path))


def test_invalid_client_id_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_ID", "not-a-uuid")
    monkeypatch.setenv("ACCOUNT_MARIA_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "maria"
        telegram_user_id = 43
        database_path = "maria.db"
        """,
    )

    with pytest.raises(RuntimeError, match="must be a UUID"):
        load_accounts(make_settings(tmp_path))


def test_duplicate_telegram_user_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for prefix in ("ACCOUNT_A", "ACCOUNT_B"):
        monkeypatch.setenv(f"{prefix}_PLUGGY_CLIENT_ID", str(uuid4()))
        monkeypatch.setenv(f"{prefix}_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "a"
        telegram_user_id = 43
        database_path = "a.db"

        [[accounts]]
        id = "b"
        telegram_user_id = 43
        database_path = "b.db"
        """,
    )

    with pytest.raises(RuntimeError, match="Duplicate telegram_user_id"):
        load_accounts(make_settings(tmp_path))


def test_duplicate_database_path_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for prefix in ("ACCOUNT_A", "ACCOUNT_B"):
        monkeypatch.setenv(f"{prefix}_PLUGGY_CLIENT_ID", str(uuid4()))
        monkeypatch.setenv(f"{prefix}_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "a"
        telegram_user_id = 42
        database_path = "same.db"

        [[accounts]]
        id = "b"
        telegram_user_id = 43
        database_path = "./same.db"
        """,
    )

    with pytest.raises(RuntimeError, match="Duplicate database_path"):
        load_accounts(make_settings(tmp_path))


def test_duplicate_env_prefix_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCOUNT_A_B_PLUGGY_CLIENT_ID", str(uuid4()))
    monkeypatch.setenv("ACCOUNT_A_B_PLUGGY_CLIENT_SECRET", "secret")
    write_accounts(
        tmp_path / "accounts.toml",
        """
        [[accounts]]
        id = "a-b"
        telegram_user_id = 42
        database_path = "a.db"

        [[accounts]]
        id = "a_b"
        telegram_user_id = 43
        database_path = "b.db"
        """,
    )

    with pytest.raises(RuntimeError, match="Duplicate env prefix"):
        load_accounts(make_settings(tmp_path))
