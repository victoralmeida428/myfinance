"""Composite banking intent router.

Keywords decide the cheap, deterministic cases. Jev is consulted only when a
sentence contains an ambiguous banking hint, so ordinary messages never pay
for an API call.
"""

from __future__ import annotations

from myfinance.application.ports import IntentRouter
from myfinance.domain.banking import BankingIntent
from myfinance.infrastructure.routing.keywords import KeywordIntentRouter


class CompositeIntentRouter:
    """Routes with keywords first and Jev only for ambiguous banking hints."""

    def __init__(
        self,
        keywords: KeywordIntentRouter,
        jev: IntentRouter | None = None,
    ) -> None:
        self._keywords = keywords
        self._jev = jev

    async def route(self, text: str) -> BankingIntent:
        keyword = await self._keywords.route(text)
        if keyword is not None:
            return keyword
        if self._jev is None:
            return BankingIntent.NONE
        return await self._jev.route(text)
