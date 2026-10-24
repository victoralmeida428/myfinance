"""Helpers shared by the application use cases."""

from __future__ import annotations

import asyncio
import unicodedata
from collections.abc import Awaitable
from typing import TypeVar

from myfinance.application.errors import ProviderError

__all__ = ["run_with_timeout", "strip_accents"]

_T = TypeVar("_T")


def strip_accents(text: str) -> str:
    """Lowercase a free-form sentence and remove its accents, using stdlib only."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


async def run_with_timeout(
    coro: Awaitable[_T], seconds: float, message: str
) -> _T:
    """Await ``coro`` within ``seconds``, converting a timeout to ``ProviderError``."""
    try:
        async with asyncio.timeout(seconds):
            return await coro
    except TimeoutError as exc:
        raise ProviderError(message) from exc
