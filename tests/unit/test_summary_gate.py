"""Unit tests for the Jev summary-intent gate and its use in the use case."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest

from myfinance.application.dto import NeedsClarification, SummaryMessage
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
)
from myfinance.config import Settings
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.infrastructure.parsing.summary_gate import JevSummaryIntentGate

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
BASE_URL = "https://api.typesafe.ai"


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        categorizer_api_token="test",
        categorizer_model="jev-latest",
        categorizer_base_url=BASE_URL,
    )


def _response(*, choice: str | None = None, answer: bool = True) -> dict[str, object]:
    answers: dict[str, object] = {}
    if answer:
        payload: dict[str, object] = {"type": "choice", "confidence": 1.0}
        if choice is not None:
            payload["choice"] = choice
        answers["intent"] = payload
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def test_gate_sends_the_expected_systemone_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response(choice="summary"))

    gate = JevSummaryIntentGate(_settings(), http_client=_client(handler))
    text = "Como estão meus gastos de hoje?"

    result = await gate.should_summarize(text)

    assert result is True
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    headers = captured["headers"]
    assert headers["authorization"] == "Bearer test"

    body = captured["body"]
    assert body["model"] == "jev-latest"
    assert body["state"] == text
    question = body["questions"]["intent"]
    assert question["type"] == "choice"
    criteria = question["criteria"]
    assert "summary" in criteria
    assert "other" in criteria


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("summary", True),
        ("other", False),
    ],
)
async def test_gate_maps_the_choice_answer(choice: str, expected: bool) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(choice=choice))

    gate = JevSummaryIntentGate(_settings(), http_client=_client(handler))

    assert await gate.should_summarize("oi") is expected


@pytest.mark.parametrize(
    "reply",
    [
        _response(answer=False),
        _response(choice="outro"),
    ],
)
async def test_gate_returns_none_for_a_missing_or_unknown_choice(
    reply: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply)

    gate = JevSummaryIntentGate(_settings(), http_client=_client(handler))

    assert await gate.should_summarize("oi") is None


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


class FakeSummaryGate:
    def __init__(
        self,
        decision: bool | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision
        self.error = error
        self.calls: list[str] = []

    async def should_summarize(self, text: str) -> bool | None:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.decision


def _entry() -> Entry:
    return Entry(
        id=uuid4(),
        kind=EntryKind.EXPENSE,
        day=TODAY,
        amount=Money(4500),
        description="almoço",
        category=Category.ALIMENTACAO,
        created_at=NOW,
    )


def _use_case(
    repository: InMemoryEntryRepository,
    gate: FakeSummaryGate | None = None,
) -> HandleMessageUseCase:
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    return HandleMessageUseCase(
        DeterministicMessageParser(resolver),
        RegisterEntryUseCase(repository, clock),
        clock,
        GetDailySummaryUseCase(repository, clock, resolver),
        PortugueseDateReferenceExtractor(),
        None,
        gate,
    )


async def test_gate_true_routes_to_the_summary_path() -> None:
    gate = FakeSummaryGate(True)
    use_case = _use_case(InMemoryEntryRepository([_entry()]), gate)

    result = await use_case.execute("me dá um resumo do dia")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY
    assert result.summary.total_expense_cents == 4500
    assert gate.calls == ["me dá um resumo do dia"]


async def test_gate_false_overrides_the_regex_fallback() -> None:
    gate = FakeSummaryGate(False)
    use_case = _use_case(InMemoryEntryRepository([_entry()]), gate)

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, NeedsClarification)
    assert gate.calls == ["quanto gastei hoje?"]


async def test_gate_none_falls_back_to_the_regex() -> None:
    use_case = _use_case(InMemoryEntryRepository([_entry()]), FakeSummaryGate(None))

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY


async def test_provider_error_falls_back_to_the_regex() -> None:
    gate = FakeSummaryGate(error=ProviderError("provider down"))
    use_case = _use_case(InMemoryEntryRepository([_entry()]), gate)

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY


async def test_absent_gate_keeps_the_regex_behaviour() -> None:
    use_case = _use_case(InMemoryEntryRepository([_entry()]))

    result = await use_case.execute("quanto gastei hoje?")

    assert isinstance(result, SummaryMessage)
    assert result.summary.day == TODAY
