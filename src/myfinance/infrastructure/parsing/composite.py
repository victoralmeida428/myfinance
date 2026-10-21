"""Parser that tries a fast primary implementation before the LLM."""

from __future__ import annotations

from datetime import date

from myfinance.application.dto import ParsedMessage
from myfinance.application.errors import ProviderError
from myfinance.application.ports import LLMGate, MessageParser


class CompositeMessageParser:
    """Uses the primary parser first and the fallback only when needed."""

    def __init__(
        self,
        primary: MessageParser,
        fallback: MessageParser | None = None,
        gate: LLMGate | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._gate = gate

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None:
        parsed = await self._primary.parse(text, today=today)
        if parsed is not None:
            return parsed
        if self._fallback is None:
            return None

        decision = None
        if self._gate is not None:
            try:
                decision = await self._gate.should_use_llm(text)
            except ProviderError:
                decision = None

        if decision is False:
            return None
        if decision is None and not any(
            character.isdigit() for character in text
        ):
            return None

        try:
            return await self._fallback.parse(text, today=today)
        except ProviderError:
            return None
