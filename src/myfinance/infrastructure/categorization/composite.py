"""Category classifier that degrades from a primary to a fallback adapter."""

from __future__ import annotations

from myfinance.application.errors import ProviderError
from myfinance.application.ports import CategoryClassifier
from myfinance.domain.categories import Category


class FallbackCategoryClassifier:
    """Uses the primary classifier unless it fails or abstains."""

    def __init__(
        self,
        primary: CategoryClassifier,
        fallback: CategoryClassifier,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def classify(self, text: str) -> Category | None:
        try:
            category = await self._primary.classify(text)
        except ProviderError:
            category = None
        if category is not None:
            return category
        return await self._fallback.classify(text)
