"""Financial entries: forecasts and expenses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from myfinance.domain.categories import Category
from myfinance.domain.exceptions import InvalidEntry
from myfinance.domain.money import Money

__all__ = ["Entry", "EntryKind"]


class EntryKind(StrEnum):
    """Whether an entry is a plan (forecast) or an actual spend (expense)."""

    FORECAST = "forecast"
    EXPENSE = "expense"


@dataclass(frozen=True, slots=True)
class Entry:
    """A single financial record attached to a day and a category."""

    id: UUID
    kind: EntryKind
    day: date
    amount: Money
    description: str
    category: Category
    created_at: datetime

    def __post_init__(self) -> None:
        description = self.description.strip()
        if not description:
            raise InvalidEntry("description must not be empty.")
        object.__setattr__(self, "description", description)
