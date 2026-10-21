"""Composition root for dependencies used by the HTTP layer."""

from __future__ import annotations

from functools import lru_cache

from myfinance.application.use_cases import (
    CreateConnectTokenUseCase,
    RegisterPluggyItemUseCase,
)
from myfinance.config import get_settings
from myfinance.infrastructure.clock import SystemClock
from myfinance.infrastructure.pluggy import PluggyConnectTokenProvider
from myfinance.infrastructure.sqlite import (
    SqliteDatabase,
    SqlitePluggyItemRepository,
)


@lru_cache
def get_connect_token_provider() -> PluggyConnectTokenProvider:
    """Return the process-wide Pluggy provider (holds the cached client)."""
    return PluggyConnectTokenProvider(get_settings())


def get_create_connect_token_use_case() -> CreateConnectTokenUseCase:
    """Build a use case per request around the shared provider."""
    return CreateConnectTokenUseCase(get_connect_token_provider())


@lru_cache
def get_sqlite_database() -> SqliteDatabase:
    """Return the process-wide SQLite database (creates the schema once)."""
    return SqliteDatabase(get_settings().database_path)


@lru_cache
def get_pluggy_item_repository() -> SqlitePluggyItemRepository:
    """Return the Pluggy item repository backed by the shared database."""
    return SqlitePluggyItemRepository(get_sqlite_database())


def get_register_pluggy_item_use_case() -> RegisterPluggyItemUseCase:
    """Build the item-registering use case per request."""
    return RegisterPluggyItemUseCase(
        get_pluggy_item_repository(),
        SystemClock(get_settings().timezone),
    )
