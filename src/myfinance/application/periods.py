"""Resolution of natural-language period references (pt-BR, stdlib only)."""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta

__all__ = ["resolve_period"]

_LAST_MONTH_MARKERS = ("mes passado", "ultimo mes")
_CURRENT_MONTH_MARKERS = (
    "esse mes",
    "este mes",
    "nesse mes",
    "neste mes",
    "mes atual",
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

    # Previous month is checked first so "mes passado" never matches the
    # current-month marker "mes".
    if _contains_any(normalized, _LAST_MONTH_MARKERS):
        return _previous_month_range(today)

    # Previous week is checked before the current-week markers so "semana
    # passada" is not mistaken for "essa semana".
    if _contains_any(normalized, _LAST_WEEK_MARKERS):
        current_monday = today - timedelta(days=today.weekday())
        return current_monday - timedelta(days=7), current_monday - timedelta(
            days=1
        )

    if _contains_any(normalized, _CURRENT_MONTH_MARKERS):
        return today.replace(day=1), today

    if _contains_any(normalized, _CURRENT_WEEK_MARKERS):
        monday = today - timedelta(days=today.weekday())
        return monday, today

    if _contains_any(normalized, _LAST_SEVEN_DAYS_MARKERS):
        return today - timedelta(days=6), today

    if _contains_any(normalized, _LAST_THIRTY_DAYS_MARKERS):
        return today - timedelta(days=29), today

    return None
