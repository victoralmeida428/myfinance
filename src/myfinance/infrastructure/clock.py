"""System clock adapter, aware of the configured timezone."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


class SystemClock:
    """Supplies the current date and time in a named timezone."""

    def __init__(self, timezone: str) -> None:
        self._timezone = ZoneInfo(timezone)

    def today(self) -> date:
        """Return the current local date."""
        return datetime.now(self._timezone).date()

    def now(self) -> datetime:
        """Return the current local time as an aware datetime."""
        return datetime.now(self._timezone)
