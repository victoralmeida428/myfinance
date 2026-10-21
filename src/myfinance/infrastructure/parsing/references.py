"""Extraction of date references from free-form pt-BR sentences.

Pure and I/O-free: it only tokenizes the sentence and delegates the lexical
recognition to :func:`myfinance.infrastructure.parsing.dates.find_date_reference`.
"""

from __future__ import annotations

from myfinance.infrastructure.parsing.dates import find_date_reference

__all__ = ["PortugueseDateReferenceExtractor"]


class PortugueseDateReferenceExtractor:
    """Finds the raw date reference named anywhere in a sentence."""

    def extract(self, text: str) -> str | None:
        """Return the normalized date reference in ``text``, or ``None``."""
        if not isinstance(text, str):
            return None
        found = find_date_reference(text.split())
        if found is None:
            return None
        reference, _consumed = found
        return reference
