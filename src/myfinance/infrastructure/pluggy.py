"""Pluggy adapter for connect-token creation.

The Pluggy SDK is blocking (urllib3), so every SDK call runs in a worker thread.
Authentication and client caching live in
:class:`myfinance.infrastructure.pluggy_client.PluggyApiClientFactory`.
"""

from __future__ import annotations

from typing import Any

import anyio
import urllib3
from pluggy_sdk import (
    ApiClient,
    ApiException,
    AuthApi,
    ConnectTokenRequest,
    ItemOptions,
)

from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.models import ClientUserId, ConnectToken
from myfinance.infrastructure.pluggy_client import PluggyApiClientFactory

_REQUEST_TIMEOUT_SECONDS = 30


class PluggyConnectTokenProvider:
    """Creates Pluggy connect tokens with a cached, auto-refreshed client."""

    def __init__(self, settings: Settings) -> None:
        self._factory = PluggyApiClientFactory(settings)

    async def create_connect_token(
        self, client_user_id: ClientUserId
    ) -> ConnectToken:
        client = await self._factory.client()
        try:
            token = await anyio.to_thread.run_sync(
                self._connect_token,
                client,
                client_user_id.value,
                abandon_on_cancel=True,
            )
        except (ApiException, urllib3.exceptions.HTTPError) as exc:
            raise ProviderError(
                "Pluggy rejected the connect token request."
            ) from exc
        return ConnectToken(token.access_token)

    @staticmethod
    def _connect_token(client: ApiClient, client_user_id: str) -> Any:
        """Blocking call: create a connect token for a client user."""
        return AuthApi(client).connect_token_create(
            ConnectTokenRequest(
                options=ItemOptions(client_user_id=client_user_id)
            ),
            _request_timeout=_REQUEST_TIMEOUT_SECONDS,
        )
