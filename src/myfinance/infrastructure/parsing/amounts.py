"""Extraction and parsing of monetary amounts in pt-BR notation.

The amount pattern is guarded against date components: a digit run touching a
``-`` or ``/`` (as in ISO and DD/MM dates) is not treated as money. Callers
should still blank the date span before searching, so the date is not left in
the description; the deterministic parser does exactly that.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from myfinance.domain.exceptions import InvalidAmount
from myfinance.domain.money import Money

_AMOUNT_RE = re.compile(
    r"(?:R\$\s*)?(?<![\w.,/-])"
    r"(?P<amount>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"(?!\w|[.,]\d|[-/])",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"^[0-9.,]+$")


def find_amount(text: str) -> re.Match[str] | None:
    """Return the first monetary amount found in ``text``.

    The returned match includes an optional ``R$`` prefix. Date spans must be
    removed by the caller before calling this function.
    """
    return _AMOUNT_RE.search(text)


def parse_amount_cents(raw: str) -> int | None:
    """Parse a pt-BR amount into integer cents, or ``None`` when invalid."""
    if not isinstance(raw, str):
        return None

    cleaned = raw.strip().lower().replace("r$", "").replace("\u00a0", "")
    cleaned = cleaned.replace(" ", "")
    if not cleaned or _NUMERIC_RE.fullmatch(cleaned) is None:
        return None

    try:
        return Money.from_reais(_to_decimal(cleaned)).cents
    except (InvalidAmount, InvalidOperation):
        return None


def _to_decimal(cleaned: str) -> Decimal:
    has_dot = "." in cleaned
    has_comma = "," in cleaned

    if has_dot and has_comma:
        # Dots group thousands; the comma is the decimal separator.
        return Decimal(cleaned.replace(".", "").replace(",", "."))

    if has_comma:
        return Decimal(cleaned.replace(",", "."))

    if has_dot:
        parts = cleaned.split(".")
        if (
            1 <= len(parts[0]) <= 3
            and all(part.isdigit() for part in parts)
            and all(len(part) == 3 for part in parts[1:])
        ):
            # A dot followed by exactly three digits after at most three
            # integer digits is a thousands separator.
            return Decimal("".join(parts))
        return Decimal(cleaned)

    return Decimal(cleaned)
