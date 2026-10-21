"""Natural-language date resolution for Brazilian Portuguese."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DMY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DM_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_FEIRA_SUFFIX_RE = re.compile(r"[-\s]+feira$")

EDGE_PUNCTUATION = ".,!?;:()[]{}\"'-+"

_RELATIVE_REFERENCES = frozenset({"hoje", "ontem", "amanha"})

_WEEKDAYS: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}


def normalize(value: str) -> str:
    """Lowercase, strip accents and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def strip_edges(token: str) -> str:
    """Remove punctuation that commonly clings to a word, keeping ``/`` and ``-``."""
    return token.strip(EDGE_PUNCTUATION)


def _weekday_name(normalized: str) -> str | None:
    name = _FEIRA_SUFFIX_RE.sub("", normalized).split("-")[0]
    return name if name in _WEEKDAYS else None


def find_date_reference(
    tokens: Sequence[str],
) -> tuple[str, frozenset[int]] | None:
    """Locate the first date expression in already-tokenized words.

    Returns the normalized reference text and the indexes of the tokens it
    consumed, or ``None`` when the words name no date.
    """
    cleaned = [strip_edges(token) for token in tokens]
    normalized = [normalize(token) for token in cleaned]
    count = len(normalized)

    for index, token in enumerate(normalized):
        if not token:
            continue

        if (
            index + 2 < count
            and token == "depois"
            and normalized[index + 1] == "de"
            and normalized[index + 2] == "amanha"
        ):
            return "depois de amanha", frozenset({index, index + 1, index + 2})

        if (
            index + 1 < count
            and _weekday_name(token) is not None
            and normalized[index + 1] == "feira"
        ):
            return _weekday_name(token) or token, frozenset({index, index + 1})

        if token in _RELATIVE_REFERENCES:
            return token, frozenset({index})

        if _ISO_RE.match(token) or _DMY_RE.match(token) or _DM_RE.match(token):
            return token, frozenset({index})

        weekday = _weekday_name(token)
        if weekday is not None:
            return weekday, frozenset({index})

    return None


class PortugueseDateResolver:
    """Resolves pt-BR date expressions without performing any I/O."""

    def resolve(self, reference: str | None, *, today: date) -> date | None:
        """Return the day named by ``reference``, or ``None`` if unknown."""
        if reference is None:
            return today

        normalized = normalize(reference)
        if not normalized:
            return today

        if normalized == "hoje":
            return today
        if normalized == "ontem":
            return today - timedelta(days=1)
        if normalized == "amanha":
            return today + timedelta(days=1)
        if normalized == "depois de amanha":
            return today + timedelta(days=2)

        iso = _ISO_RE.match(normalized)
        if iso is not None:
            return self._build(int(iso[1]), int(iso[2]), int(iso[3]))

        dmy = _DMY_RE.match(normalized)
        if dmy is not None:
            return self._build(int(dmy[3]), int(dmy[2]), int(dmy[1]))

        dm = _DM_RE.match(normalized)
        if dm is not None:
            return self._build(today.year, int(dm[2]), int(dm[1]))

        weekday = self._weekday(normalized)
        if weekday is not None:
            delta = (weekday - today.weekday()) % 7
            return today + timedelta(days=delta)

        return None

    @staticmethod
    def _build(year: int, month: int, day: int) -> date | None:
        try:
            return date(year, month, day)
        except ValueError:
            return None

    @staticmethod
    def _weekday(normalized: str) -> int | None:
        name = _FEIRA_SUFFIX_RE.sub("", normalized)
        return _WEEKDAYS.get(name)
