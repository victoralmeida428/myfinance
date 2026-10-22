"""Unit tests for the Telegram update handlers (no network, no real bot)."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
)
from myfinance.domain.banking import BankExpense
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
from myfinance.presentation.telegram.commands import HELP_TEXT
from myfinance.presentation.telegram.handlers import BotHandlers

TODAY = date(2026, 10, 20)
YESTERDAY = date(2026, 10, 19)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now


class InMemoryEntryRepository:
    def __init__(self) -> None:
        self.entries: list[Entry] = []

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)


class InMemoryProcessedUpdates:
    def __init__(self) -> None:
        self.seen: set[int] = set()

    async def claim(self, update_id: int) -> bool:
        if update_id in self.seen:
            return False
        self.seen.add(update_id)
        return True


class FakeMessage:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeExplainer:
    """Records the question and error, then returns or raises a fixed reply."""

    def __init__(
        self,
        reply: str = "O banco não respondeu. Tente novamente.",
        *,
        error: ProviderError | None = None,
    ) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, Exception]] = []

    async def execute(self, *, question: str, error: Exception) -> str:
        self.calls.append((question, error))
        if self.error is not None:
            raise self.error
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


def make_entry(day: date) -> Entry:
    return Entry(
        id=uuid4(),
        kind=EntryKind.EXPENSE,
        day=day,
        amount=Money(4500),
        description="almoço",
        category=Category.ALIMENTACAO,
        created_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    )


def build_handlers(
    repository: InMemoryEntryRepository | None = None,
    updates: InMemoryProcessedUpdates | None = None,
    explain_failure: FakeExplainer | None = None,
    bank_expenses: FailingBankExpenses | None = None,
) -> tuple[BotHandlers, InMemoryEntryRepository, InMemoryProcessedUpdates]:
    repository = repository or InMemoryEntryRepository()
    updates = updates or InMemoryProcessedUpdates()
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    register = RegisterEntryUseCase(repository, clock)
    summary = GetDailySummaryUseCase(
        repository, clock, resolver, bank_expenses
    )
    handlers = BotHandlers(
        handle_message=HandleMessageUseCase(
            DeterministicMessageParser(resolver),
            register,
            clock,
            summary,
            PortugueseDateReferenceExtractor(),
        ),
        summary=summary,
        details=GetDayDetailsUseCase(repository, clock, resolver),
        updates=updates,
        explain_failure=explain_failure,
    )
    return handlers, repository, updates


def make_update(update_id: int, text: str | None = None):
    message = FakeMessage(text)
    update = SimpleNamespace(update_id=update_id, effective_message=message)
    return update, message


def context(args: list[str] | None = None) -> Any:
    return SimpleNamespace(args=args)


async def test_message_registers_an_expense() -> None:
    handlers, repository, _updates = build_handlers()
    update, message = make_update(1, "Almoço hoje 45")

    await handlers.message(update, context())

    assert len(message.replies) == 1
    assert "Despesa registrada" in message.replies[0]
    assert len(repository.entries) == 1


async def test_message_is_deduplicated_by_update_id() -> None:
    handlers, repository, _updates = build_handlers()
    update, message = make_update(7, "Almoço hoje 45")

    await handlers.message(update, context())
    await handlers.message(update, context())

    assert len(message.replies) == 1
    assert len(repository.entries) == 1


async def test_message_answers_a_summary_question() -> None:
    repository = InMemoryEntryRepository()
    repository.entries.append(make_entry(TODAY))
    handlers, _repository, _updates = build_handlers(repository)
    update, message = make_update(2, "Como estão meus gastos de hoje?")

    await handlers.message(update, context())

    assert "Resumo de" in message.replies[0]


async def test_message_asks_for_clarification_when_unparseable() -> None:
    handlers, _repository, _updates = build_handlers()
    update, message = make_update(3, "oi tudo bem")

    await handlers.message(update, context())

    assert "Não consegui identificar valor e data" in message.replies[0]


async def test_summary_handler_resolves_relative_dates() -> None:
    repository = InMemoryEntryRepository()
    repository.entries.append(make_entry(YESTERDAY))
    handlers, _repository, _updates = build_handlers(repository)
    update, message = make_update(4)

    await handlers.summary(update, context(["ontem"]))

    assert "Resumo de" in message.replies[0]


async def test_summary_handler_rejects_an_unknown_date() -> None:
    handlers, _repository, _updates = build_handlers()
    update, message = make_update(5)

    await handlers.summary(update, context(["banana"]))

    assert "Não entendi a data." in message.replies[0]


async def test_unsupported_messages_are_rejected_politely() -> None:
    handlers, _repository, _updates = build_handlers()
    update, message = make_update(6)

    await handlers.unsupported(update, context())

    assert "só entendo mensagens de texto" in message.replies[0]


async def test_start_replies_with_the_help_text() -> None:
    handlers, _repository, _updates = build_handlers()
    update, message = make_update(8)

    await handlers.start(update, context())

    assert message.replies == [HELP_TEXT]


async def test_help_replies_with_the_help_text() -> None:
    handlers, _repository, _updates = build_handlers()
    update, message = make_update(9)

    await handlers.help(update, context())

    assert message.replies == [HELP_TEXT]


async def test_message_explains_a_bank_provider_failure() -> None:
    explainer = FakeExplainer("O banco não respondeu. Tente novamente.")
    handlers, _repository, _updates = build_handlers(
        explain_failure=explainer,
        bank_expenses=FailingBankExpenses(),
    )
    question = "Como estão meus gastos de hoje?"
    update, message = make_update(10, question)

    await handlers.message(update, context())

    assert message.replies == [explainer.reply]
    asked, error = explainer.calls[0]
    assert asked == question
    assert isinstance(error, ProviderError)


async def test_message_falls_back_when_the_explainer_fails() -> None:
    explainer = FakeExplainer(error=ProviderError("llm down"))
    handlers, _repository, _updates = build_handlers(
        explain_failure=explainer,
        bank_expenses=FailingBankExpenses(),
    )
    update, message = make_update(11, "Como estão meus gastos de hoje?")

    await handlers.message(update, context())

    assert message.replies == ["Não consegui concluir agora. Tente novamente."]
