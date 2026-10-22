"""Resolution of natural-language period references (pt-BR, stdlib only)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

__all__ = ["resolve_period"]

_LAST_MONTH_MARKERS = ("mes passado", "ultimo mes")
_NEXT_MONTH_MARKERS = ("mes que vem", "proximo mes")
_CURRENT_MONTH_MARKERS = (
    "esse mes",
    "este mes",
    "nesse mes",
    "neste mes",
    "desse mes",
    "deste mes",
    "mes atual",
    "do mes",
    "no mes",
)
_CURRENT_WEEK_MARKERS = (
    "essa semana",
    "esta semana",
    "nessa semana",
    "nesta semana",
    "semana atual",
)
_LAST_WEEK_MARKERS = ("semana passada", "semana anterior")
_LAST_SEVEN_DAYS_MARKERS = ("ultimos 7 dias", "ultima semana")
_LAST_THIRTY_DAYS_MARKERS = ("ultimos 30 dias",)

_MONTH_NAMES: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MONTH_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\b"
    r"(?:\s*(?:de\s+|/)\s*(\d{4}))?"
)


def _normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def _contains_any(normalized: str, markers: tuple[str, ...]) -> bool:
    return any(marker in normalized for marker in markers)


def _previous_month_range(today: date) -> tuple[date, date]:
    last_day_of_previous = today.replace(day=1) - timedelta(days=1)
    start = last_day_of_previous.replace(day=1)
    return start, last_day_of_previous


def _next_month_range(today: date) -> tuple[date, date]:
    start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def _month_name_range(
    normalized: str, *, today: date
) -> tuple[date, date] | None:
    """Resolve a named month, with or without an explicit year.

    Without a year the most recent non-future occurrence is used: the current
    year when the month is not later than ``today``'s month, otherwise the
    previous year.
    """
    match = _MONTH_NAME_PATTERN.search(normalized)
    if match is None:
        return None

    month = _MONTH_NAMES[match.group(1)]
    explicit_year = match.group(2)
    if explicit_year is not None:
        year = int(explicit_year)
        if not 1 <= year <= 9999:
            return None
    elif month <= today.month:
        year = today.year
    else:
        year = today.year - 1

    start = date(year, month, 1)
    if year == today.year and month == today.month:
        return start, today

    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def resolve_period(
    reference: str | None, *, today: date
) -> tuple[date, date] | None:
    """Return the inclusive ``(start, end)`` range named by ``reference``.

    Only whole phrases are recognised; a missing, blank or unknown reference
    yields ``None`` so callers can fall back to a single-day summary.
    """
    if reference is None:
        return None

    normalized = _normalize(reference)
    if not normalized:
        return None

    # Previous and next month are checked before the current-month markers:
    # both "mes passado" and "mes que vem" contain the "do mes"/"no mes"
    # fragments, which would otherwise resolve to the current month.
    if _contains_any(normalized, _LAST_MONTH_MARKERS):
        return _previous_month_range(today)

    if _contains_any(normalized, _NEXT_MONTH_MARKERS):
        return _next_month_range(today)

    if _contains_any(normalized, _CURRENT_MONTH_MARKERS):
        return today.replace(day=1), today

    # Previous week is checked before the current-week markers so "semana
    # passada" is not mistaken for "essa semana".
    if _contains_any(normalized, _LAST_WEEK_MARKERS):
        current_monday = today - timedelta(days=today.weekday())
        return current_monday - timedelta(days=7), current_monday - timedelta(
            days=1
        )

    if _contains_any(normalized, _CURRENT_WEEK_MARKERS):
        monday = today - timedelta(days=today.weekday())
        return monday, today

    if _contains_any(normalized, _LAST_SEVEN_DAYS_MARKERS):
        return today - timedelta(days=6), today

    if _contains_any(normalized, _LAST_THIRTY_DAYS_MARKERS):
        return today - timedelta(days=29), today

    return _month_name_range(normalized, today=today)
