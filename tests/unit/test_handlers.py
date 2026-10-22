"""Unit tests for the Telegram update handlers (no network, no real bot)."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from myfinance.application.dto import SpendingAnswerMessage
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
from myfinance.domain.models import ChatMessage
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


class FakeHandleMessage:
    """Returns a fixed result and records the free-form text it received."""

    def __init__(self, result: SpendingAnswerMessage) -> None:
        self._result = result
        self.calls: list[str] = []

    async def execute(self, text: str) -> SpendingAnswerMessage:
        self.calls.append(text)
        return self._result


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


class FakeMemory:
    """An in-memory ConversationMemory that records what the handler stores."""

    def __init__(self, rows: list[ChatMessage] | None = None) -> None:
        self.rows = list(rows or [])
        self.appended: list[tuple[str, str, str]] = []

    async def append(self, chat_id: str, role: str, content: str) -> None:
        self.appended.append((chat_id, role, content))
        self.rows.append(ChatMessage(role=role, content=content))

    async def recent(
        self, chat_id: str, *, exchanges: int = 5
    ) -> tuple[ChatMessage, ...]:
        return tuple(self.rows[-exchanges * 2 :])

    async def clear(self, chat_id: str) -> None:
        self.rows.clear()


class FakeFollowUp:
    """A FollowUpResolver that returns a canned rewrite and records calls."""

    def __init__(self, rewritten: str | None = "pergunta reescrita") -> None:
        self.rewritten = rewritten
        self.calls: list[tuple[str, tuple[ChatMessage, ...]]] = []

    async def rewrite(
        self, text: str, history: tuple[ChatMessage, ...] | list[ChatMessage]
    ) -> str | None:
        self.calls.append((text, tuple(history)))
        return self.rewritten


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
    memory: FakeMemory | None = None,
    follow_up: FakeFollowUp | None = None,
    handle_message: FakeHandleMessage | None = None,
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
        handle_message=handle_message
        or HandleMessageUseCase(
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
        memory=memory,
        follow_up=follow_up,
    )
    return handlers, repository, updates


def make_update(update_id: int, text: str | None = None):
    message = FakeMessage(text)
    update = SimpleNamespace(
        update_id=update_id,
        effective_message=message,
        effective_chat=SimpleNamespace(id=update_id),
        effective_user=SimpleNamespace(id=update_id),
    )
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


async def test_message_replies_with_a_spending_answer() -> None:
    answer = SpendingAnswerMessage(
        start=date(2026, 10, 1),
        end=date(2026, 10, 22),
        label="Uber",
        total_cents=34250,
        count=12,
        category=None,
        keywords=("uber",),
    )
    handler = FakeHandleMessage(answer)
    repository = InMemoryEntryRepository()
    clock = FixedClock(NOW)
    resolver = PortugueseDateResolver()
    handlers = BotHandlers(
        handle_message=handler,
        summary=GetDailySummaryUseCase(repository, clock, resolver),
        details=GetDayDetailsUseCase(repository, clock, resolver),
        updates=InMemoryProcessedUpdates(),
    )
    question = "Quanto gastei com Uber?"
    update, message = make_update(12, question)

    await handlers.message(update, context())

    assert message.replies == [
        "Você gastou R$ 342,50 com Uber de 01/10/2026 a 22/10/2026 "
        "(12 lançamentos)."
    ]
    assert handler.calls == [question]


def spending_answer() -> SpendingAnswerMessage:
    return SpendingAnswerMessage(
        start=date(2026, 10, 1),
        end=date(2026, 10, 22),
        label="Uber",
        total_cents=34250,
        count=12,
        category=None,
        keywords=("uber",),
    )


async def test_elliptical_follow_up_uses_the_rewritten_question() -> None:
    handle = FakeHandleMessage(spending_answer())
    memory = FakeMemory(
        [
            ChatMessage(role="user", content="Quanto gastei com Uber?"),
            ChatMessage(
                role="assistant", content="Você gastou R$ 342,50 com Uber."
            ),
        ]
    )
    follow_up = FakeFollowUp("quanto gastei de uber no cartão?")
    handlers, _repository, _updates = build_handlers(
        memory=memory, follow_up=follow_up, handle_message=handle
    )
    update, message = make_update(20, "e no cartão?")

    await handlers.message(update, context())

    assert handle.calls == ["quanto gastei de uber no cartão?"]
    assert follow_up.calls == [
        (
            "e no cartão?",
            (
                ChatMessage(role="user", content="Quanto gastei com Uber?"),
                ChatMessage(
                    role="assistant",
                    content="Você gastou R$ 342,50 com Uber.",
                ),
            ),
        )
    ]
    assert memory.appended == [
        ("20", "user", "e no cartão?"),
        ("20", "assistant", message.replies[0]),
    ]


async def test_without_history_the_message_is_not_rewritten() -> None:
    handle = FakeHandleMessage(spending_answer())
    memory = FakeMemory()
    follow_up = FakeFollowUp("quanto gastei de uber no cartão?")
    handlers, _repository, _updates = build_handlers(
        memory=memory, follow_up=follow_up, handle_message=handle
    )
    update, message = make_update(21, "e no cartão?")

    await handlers.message(update, context())

    assert follow_up.calls == []
    assert handle.calls == ["e no cartão?"]
    assert memory.appended == [
        ("21", "user", "e no cartão?"),
        ("21", "assistant", message.replies[0]),
    ]


async def test_memory_none_keeps_the_previous_behavior() -> None:
    handle = FakeHandleMessage(spending_answer())
    follow_up = FakeFollowUp("quanto gastei de uber no cartão?")
    handlers, _repository, _updates = build_handlers(
        follow_up=follow_up, handle_message=handle
    )
    update, message = make_update(22, "e no cartão?")

    await handlers.message(update, context())

    assert follow_up.calls == []
    assert handle.calls == ["e no cartão?"]
    assert len(message.replies) == 1
