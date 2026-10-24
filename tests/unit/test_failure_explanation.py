"""Unit tests for the LLM error-explanation fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    ExplainFailureUseCase,
    GetDailySummaryUseCase,
    GetPeriodSummaryUseCase,
)
from myfinance.domain.banking import BankExpense
from myfinance.domain.entries import Entry
from myfinance.domain.models import ChatMessage
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now


class InMemoryEntryRepository:
    def __init__(self, entries: list[Entry] | None = None) -> None:
        self.entries: list[Entry] = list(entries or [])

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class RecordingLanguageModel:
    """Records the messages it receives and returns a fixed answer."""

    def __init__(
        self,
        reply: str = "Não foi possível concluir.",
        *,
        delay: float = 0.0,
    ) -> None:
        self.reply = reply
        self.delay = delay
        self.calls: list[tuple[ChatMessage, ...]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str:
        self.calls.append(tuple(messages))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.reply


class FailingBankExpenses:
    """A BankExpenseProvider that always reports the bank as unavailable."""

    def __init__(self, message: str = "pluggy down") -> None:
        self._message = message
        self.calls: list[tuple[date, date]] = []

    async def expenses(
        self, start: date, end: date
    ) -> tuple[BankExpense, ...]:
        self.calls.append((start, end))
        raise ProviderError(self._message)


async def test_explanation_sends_the_question_and_the_error() -> None:
    model = RecordingLanguageModel("Não consegui falar com o banco.")
    use_case = ExplainFailureUseCase(model)

    result = await use_case.execute(
        question="Quanto gastei hoje?", error=ProviderError("pluggy down")
    )

    assert result == "Não consegui falar com o banco."
    system, user = model.calls[0]
    assert system.role == "system"
    assert "português" in system.content
    assert user.role == "user"
    assert "Quanto gastei hoje?" in user.content
    assert "ProviderError: pluggy down" in user.content


async def test_blank_explanation_raises_provider_error() -> None:
    model = RecordingLanguageModel("   ")
    use_case = ExplainFailureUseCase(model)

    with pytest.raises(ProviderError):
        await use_case.execute(
            question="Quanto gastei hoje?", error=ProviderError("pluggy down")
        )


async def test_slow_explanation_times_out() -> None:
    model = RecordingLanguageModel("tarde demais", delay=0.05)
    use_case = ExplainFailureUseCase(model, timeout_seconds=0.01)

    with pytest.raises(ProviderError):
        await use_case.execute(
            question="Quanto gastei hoje?", error=ProviderError("pluggy down")
        )


async def test_daily_summary_propagates_a_provider_error() -> None:
    use_case = GetDailySummaryUseCase(
        InMemoryEntryRepository(),
        FixedClock(NOW),
        PortugueseDateResolver(),
        FailingBankExpenses(),
    )

    with pytest.raises(ProviderError, match="pluggy down"):
        await use_case.execute(None)


async def test_period_summary_propagates_a_provider_error() -> None:
    use_case = GetPeriodSummaryUseCase(
        InMemoryEntryRepository(),
        FixedClock(NOW),
        FailingBankExpenses(),
    )

    with pytest.raises(ProviderError, match="pluggy down"):
        await use_case.execute("esse mes")
