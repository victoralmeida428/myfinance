"""OpenCode adapter for chat completions (OpenAI-compatible API)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

import openai
from openai import AsyncOpenAI

from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.models import ChatMessage

_USER_AGENT = "myfinance/0.1.0"


class OpenCodeLanguageModel:
    """Language model backed by the OpenCode inference API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None
        self._blocked_until = 0.0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str:
        if time.monotonic() < self._blocked_until:
            raise ProviderError("OpenCode is rate limited; using local parsing.")
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self._settings.opencode_model,
                messages=[message.as_dict() for message in messages],
                extra_headers=self._headers(session_id),
            )
        except openai.RateLimitError as exc:
            self._blocked_until = time.monotonic() + 60
            raise ProviderError("OpenCode rate limit reached.") from exc
        except openai.OpenAIError as exc:
            raise ProviderError("OpenCode inference request failed.") from exc
        return response.choices[0].message.content or ""

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=self._settings.opencode_base_url.rstrip("/"),
                api_key=self._api_key(),
                default_headers={"User-Agent": _USER_AGENT},
                max_retries=0,
            )
        return self._client

    def _api_key(self) -> str:
        secret = self._settings.opencode_api_key
        if secret is None or not secret.get_secret_value():
            raise ProviderError(
                "Missing OPENCODE_API_KEY. Create one in the OpenCode Console "
                "(https://opencode.ai/console) and set it in your environment; "
                "never commit it or send it to the browser."
            )
        return secret.get_secret_value()

    def _headers(self, session_id: str | None) -> dict[str, str]:
        headers = {"User-Agent": _USER_AGENT}
        # Only the Go surface requires a stable per-conversation session id.
        if "/go/" in self._settings.opencode_base_url:
            headers["x-opencode-session"] = session_id or str(uuid.uuid4())
        return headers
