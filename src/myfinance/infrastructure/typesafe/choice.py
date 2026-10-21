"""Generic TypeSafe System One ``choice`` client.

System One takes a free-form ``state`` plus typed questions and returns typed
answers. This adapter sends a single choice question and returns the raw choice
label; callers decide what the label means. It stays quiet and returns ``None``
whenever the token is absent, the provider fails, or the reply is malformed.
"""

from __future__ import annotations

import httpx

from myfinance.config import Settings

__all__ = ["SystemOneChoiceClient"]

_DISABLING_STATUS_CODES = frozenset({401, 402, 403})


def _argmax_choice(probabilities: object) -> str | None:
    """Return the most likely label from a probabilities mapping."""
    if not isinstance(probabilities, dict):
        return None

    best_key: str | None = None
    best_value = float("-inf")

    for key, value in probabilities.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        score = float(value)
        if score > best_value:
            best_key = key
            best_value = score

    return best_key


def _parse_choice(payload: object, question_id: str, criteria: dict[str, str]) -> str | None:
    """Read a raw choice label out of a System One response."""
    if not isinstance(payload, dict):
        return None
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return None
    answer = answers.get(question_id)
    if not isinstance(answer, dict):
        return None

    choice = answer.get("choice")
    if isinstance(choice, str) and choice in criteria:
        return choice

    # A reply outside the declared criteria is unusable as a label; prefer the
    # most likely declared alternative when the model reports probabilities.
    fallback = _argmax_choice(answer.get("probabilities"))
    if fallback is not None:
        return fallback

    if isinstance(choice, str):
        return choice
    return None


class SystemOneChoiceClient:
    """Asks one TypeSafe System One choice question per call."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._disabled = False

    async def choose(
        self,
        *,
        state: str,
        question_id: str,
        instructions: str,
        criteria: dict[str, str],
        model: str | None = None,
    ) -> str | None:
        """Return the raw chosen label, or ``None`` when the model abstains."""
        if self._disabled:
            return None

        token = self._token()
        if token is None:
            return None

        body = {
            "state": state,
            "model": model or self._settings.categorizer_model,
            "questions": {
                question_id: {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": dict(criteria),
                }
            },
        }

        try:
            response = await self._client().post(
                f"{self._settings.categorizer_base_url.rstrip('/')}/v1/systemone",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _DISABLING_STATUS_CODES:
                self._disabled = True
            return None
        except (httpx.HTTPError, ValueError):
            return None

        return _parse_choice(payload, question_id, criteria)

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30)
        return self._http_client

    def _token(self) -> str | None:
        secret = self._settings.categorizer_api_token
        if secret is None:
            return None
        token = secret.get_secret_value().strip()
        return token or None
