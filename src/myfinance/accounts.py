"""Per-account configuration loaded from a secret ``accounts.toml``."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import UUID

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    SecretStr,
    ValidationError,
    model_validator,
)

from myfinance.config import Settings

__all__ = [
    "AccountConfig",
    "AccountPluggyItem",
    "AccountProfile",
    "AccountsFile",
    "load_accounts",
]


class AccountPluggyItem(BaseModel):
    """One Pluggy item connected to an account."""

    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    connector_name: str | None = None


class AccountConfig(BaseModel):
    """One ``[[accounts]]`` entry, with credentials referenced by env name."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str | None = None
    telegram_user_id: PositiveInt
    database_path: Path
    pluggy_items: list[AccountPluggyItem] = Field(default_factory=list)
    pluggy_item_id: UUID | None = None
    pluggy_connector_name: str | None = None
    pluggy_client_id_env: str | None = None
    pluggy_client_secret_env: str | None = None

    @model_validator(mode="after")
    def _validate_pluggy_items(self) -> Self:
        if self.pluggy_items and (
            self.pluggy_item_id is not None
            or self.pluggy_connector_name is not None
        ):
            raise ValueError(
                "use pluggy_items or the legacy pluggy_item_id/"
                "pluggy_connector_name fields, not both"
            )
        item_ids = [item.item_id for item in self.pluggy_items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate pluggy_item_id in pluggy_items")
        return self


class AccountsFile(BaseModel):
    """The parsed ``accounts.toml`` document."""

    model_config = ConfigDict(extra="forbid")

    accounts: list[AccountConfig] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class AccountProfile:
    """An account ready to build its own container and SQLite database."""

    id: str
    name: str
    telegram_user_id: int
    settings: Settings
    pluggy_items: tuple[AccountPluggyItem, ...] = ()


def load_accounts(settings: Settings) -> tuple[AccountProfile, ...]:
    """Load every configured account, resolving credentials from the environment."""
    path = settings.accounts_file
    if not path.exists():
        raise RuntimeError(
            f"Missing {path}. Copy accounts.example.toml and keep it secret."
        )
    if not path.is_file():
        raise RuntimeError(f"{path} must be a regular file, not a directory.")

    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Invalid TOML in {path}: {exc}") from exc

    try:
        parsed = AccountsFile.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid account configuration in {path}: {exc}") from exc

    environment = _environment(settings)
    profiles = tuple(
        _build_profile(account, path.parent, settings, environment)
        for account in parsed.accounts
    )
    _validate_unique(profiles)
    return profiles


def _build_profile(
    account: AccountConfig,
    root: Path,
    base: Settings,
    environment: Mapping[str, str],
) -> AccountProfile:
    prefix = _env_prefix(account.id)
    client_id_env = account.pluggy_client_id_env or f"{prefix}_PLUGGY_CLIENT_ID"
    client_secret_env = (
        account.pluggy_client_secret_env or f"{prefix}_PLUGGY_CLIENT_SECRET"
    )

    raw_client_id = _read_env(client_id_env, account.id, environment)
    try:
        client_id = UUID(raw_client_id)
    except ValueError as exc:
        raise RuntimeError(
            f"Account '{account.id}': {client_id_env} must be a UUID."
        ) from exc
    client_secret = SecretStr(
        _read_env(client_secret_env, account.id, environment)
    )

    database_path = account.database_path
    if not database_path.is_absolute():
        database_path = (root / database_path).resolve()

    pluggy_items = _pluggy_items(account)
    first_item = pluggy_items[0] if pluggy_items else None
    account_settings = base.model_copy(
        update={
            "pluggy_client_id": client_id,
            "pluggy_client_secret": client_secret,
            "pluggy_item_id": first_item.item_id if first_item else None,
            "pluggy_connector_name": (
                first_item.connector_name if first_item else None
            ),
            "database_path": database_path,
            "telegram_owner_id": account.telegram_user_id,
        }
    )

    return AccountProfile(
        id=account.id,
        name=account.name or account.id,
        telegram_user_id=account.telegram_user_id,
        settings=account_settings,
        pluggy_items=pluggy_items,
    )


def _pluggy_items(
    account: AccountConfig,
) -> tuple[AccountPluggyItem, ...]:
    if account.pluggy_items:
        return tuple(account.pluggy_items)
    if account.pluggy_item_id is None:
        return ()
    return (
        AccountPluggyItem(
            item_id=account.pluggy_item_id,
            connector_name=account.pluggy_connector_name,
        ),
    )


def _environment(settings: Settings) -> Mapping[str, str]:
    """Merge the configured .env file with the process environment."""
    values: dict[str, str] = {}
    env_file = settings.model_config.get("env_file")
    for candidate in _env_files(env_file):
        values.update(
            {
                key: value
                for key, value in dotenv_values(candidate).items()
                if value is not None
            }
        )
    values.update(os.environ)
    return values


def _env_files(env_file: object) -> tuple[Path, ...]:
    if env_file is None:
        return ()
    if isinstance(env_file, (str, Path)):
        return (Path(env_file),)
    if isinstance(env_file, (list, tuple)):
        return tuple(Path(item) for item in env_file if item is not None)
    return ()


def _read_env(name: str, account_id: str, environment: Mapping[str, str]) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Account '{account_id}': set {name} in the environment."
        )
    return value


def _env_prefix(account_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", account_id).strip("_").upper()
    if not normalized:
        raise RuntimeError(f"Invalid account id {account_id!r}.")
    return f"ACCOUNT_{normalized}"


def _validate_unique(profiles: Iterable[AccountProfile]) -> None:
    profile_list = tuple(profiles)
    _ensure_unique((profile.id for profile in profile_list), "id")
    _ensure_unique(
        (profile.telegram_user_id for profile in profile_list),
        "telegram_user_id",
    )
    _ensure_unique(
        (profile.settings.database_path for profile in profile_list),
        "database_path",
    )
    _ensure_unique(
        (_env_prefix(profile.id) for profile in profile_list), "env prefix"
    )


def _ensure_unique(values: Iterable[object], label: str) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise RuntimeError(
                f"Duplicate {label} in accounts configuration: {value!r}."
            )
        seen.add(value)
