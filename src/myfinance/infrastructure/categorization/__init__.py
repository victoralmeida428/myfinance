"""Expense category classification adapters."""

from __future__ import annotations

from myfinance.infrastructure.categorization.composite import (
    FallbackCategoryClassifier,
)
from myfinance.infrastructure.categorization.jev import JevCategoryClassifier
from myfinance.infrastructure.categorization.keywords import (
    CATEGORY_KEYWORDS,
    KeywordCategoryClassifier,
    classify_keywords,
)

__all__ = [
    "CATEGORY_KEYWORDS",
    "FallbackCategoryClassifier",
    "JevCategoryClassifier",
    "KeywordCategoryClassifier",
    "classify_keywords",
]
