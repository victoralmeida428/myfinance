"""Application settings loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pluggy_client_id: UUID | None = None
    pluggy_client_secret: SecretStr | None = None
    pluggy_base_url: str = "https://api.pluggy.ai"
    pluggy_webhook_secret: SecretStr | None = None
    pluggy_item_id: UUID | None = None
    pluggy_connector_name: str | None = None
    opencode_api_key: SecretStr | None = None
    opencode_base_url: str = "https://opencode.ai/inference/go/openai/v1"
    opencode_model: str = "deepseek-v4.1-flash"
    categorizer_api_token: SecretStr | None = None
    categorizer_base_url: str = "https://api.typesafe.ai"
    categorizer_model: str = "jev-latest"
    telegram_bot_token: SecretStr | None = None
    telegram_owner_id: int | None = None
    database_path: Path = Path("myfinance.db")
    timezone: str = "America/Sao_Paulo"


def pluggy_credentials(settings: Settings) -> tuple[UUID, SecretStr]:
    """Return the Pluggy credentials, failing loudly when they are missing."""
    if settings.pluggy_client_id is None or settings.pluggy_client_secret is None:
        raise RuntimeError(
            "Missing PLUGGY_CLIENT_ID / PLUGGY_CLIENT_SECRET. "
            "Set them in the environment; never commit them."
        )
    return settings.pluggy_client_id, settings.pluggy_client_secret


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
