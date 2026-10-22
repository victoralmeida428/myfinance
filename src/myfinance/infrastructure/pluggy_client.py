"""Shared cached Pluggy API client factory.

The Pluggy SDK is blocking (urllib3), so authentication runs in a worker thread
and the resulting client is cached until shortly before the API key expires.
Both the connect-token adapter and the banking adapter share this factory.
"""

from __future__ import annotations

import asyncio
import time

import anyio
import urllib3
from pluggy_sdk import ApiClient, ApiException, AuthApi, AuthRequest, Configuration

from myfinance.application.errors import ProviderError
from myfinance.config import Settings, pluggy_credentials

__all__ = ["PluggyApiClientFactory"]

_API_KEY_TTL_SECONDS = 110 * 60
_REQUEST_TIMEOUT_SECONDS = 30


class PluggyApiClientFactory:
    """Mints and caches an authenticated Pluggy :class:`ApiClient`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client_id, self._client_secret = pluggy_credentials(settings)
        self._lock = asyncio.Lock()
        self._cached_client: ApiClient | None = None
        self._expires_at = 0.0

    async def client(self) -> ApiClient:
        """Return a client holding a valid API key, minting one when needed."""
        async with self._lock:
            if (
                self._cached_client is not None
                and time.monotonic() < self._expires_at
            ):
                return self._cached_client

            try:
                api_key = await anyio.to_thread.run_sync(
                    self._authenticate, abandon_on_cancel=True
                )
            except (ApiException, urllib3.exceptions.HTTPError) as exc:
                raise ProviderError("Pluggy authentication failed.") from exc

            configuration = Configuration(host=self._settings.pluggy_base_url)
            configuration.api_key["default"] = api_key
            self._cached_client = ApiClient(configuration)
            self._expires_at = time.monotonic() + _API_KEY_TTL_SECONDS
            return self._cached_client

    def _authenticate(self) -> str:
        """Blocking call: exchange client credentials for an API key."""
        return (
            AuthApi(
                ApiClient(Configuration(host=self._settings.pluggy_base_url))
            )
            .auth_create(
                AuthRequest(
                    client_id=self._client_id,
                    client_secret=self._client_secret.get_secret_value(),
                ),
                _request_timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            .api_key
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(client_id={self._client_id!r})"
