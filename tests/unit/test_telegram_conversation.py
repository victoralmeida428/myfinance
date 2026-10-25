"""Unit tests for the Telegram conversation flow."""

from __future__ import annotations

from datetime import date

from myfinance.application.dto import NeedsClarification, SpendingAnswerMessage
from myfinance.application.errors import ProviderError
from myfinance.domain.models import ChatMessage
from myfinance.infrastructure.parsing.follow_up import looks_like_follow_up
from myfinance.presentation.telegram.conversation import TelegramConversation


class FakeIncoming:
    def __init__(
        self,
        reply: NeedsClarification | SpendingAnswerMessage | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._reply = reply or NeedsClarification("preciso de mais contexto")
        self._error = error
        self.calls: list[str] = []

    async def execute(self, text: str):
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return self._reply


class FakeMemory:
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
    def __init__(self, rewritten: str = "quanto gastei com uber?") -> None:
        self._rewritten = rewritten
        self.calls: list[str] = []

    def should_rewrite(self, text: str) -> bool:
        return True

    async def rewrite(self, text: str, history) -> str:
        self.calls.append(text)
        return self._rewritten


class HeuristicFollowUp(FakeFollowUp):
    def should_rewrite(self, text: str) -> bool:
        return looks_like_follow_up(text)


class FakeExplainer:
    def __init__(self, reply: str = "O banco não respondeu.") -> None:
        self.reply = reply
        self.calls: list[tuple[str, Exception]] = []

    async def execute(self, *, question: str, error: Exception) -> str:
        self.calls.append((question, error))
        return self.reply


async def test_short_message_with_history_is_rewritten_and_remembered() -> None:
    incoming = FakeIncoming()
    memory = FakeMemory(
        [ChatMessage(role="user", content="Quanto gastei com uber?")]
    )
    follow_up = FakeFollowUp()
    conversation = TelegramConversation(
        incoming=incoming,  # type: ignore[arg-type]
        memory=memory,
        follow_up=follow_up,  # type: ignore[arg-type]
    )

    answer = await conversation.respond("chat", "e no cartão?")

    assert incoming.calls == ["quanto gastei com uber?"]
    assert follow_up.calls == ["e no cartão?"]
    assert answer == "preciso de mais contexto"
    assert memory.appended == [
        ("chat", "user", "e no cartão?"),
        ("chat", "assistant", "preciso de mais contexto"),
    ]


async def test_complete_summary_is_not_rewritten_with_history() -> None:
    incoming = FakeIncoming()
    memory = FakeMemory(
        [
            ChatMessage(role="user", content="Quanto gastei com uber?"),
            ChatMessage(role="assistant", content="Você gastou R$ 10,00."),
        ]
    )
    follow_up = HeuristicFollowUp()
    conversation = TelegramConversation(
        incoming=incoming,  # type: ignore[arg-type]
        memory=memory,
        follow_up=follow_up,  # type: ignore[arg-type]
    )

    await conversation.respond("chat", "Resumo da semana")

    assert follow_up.calls == []
    assert incoming.calls == ["Resumo da semana"]


async def test_comparison_follow_up_is_rewritten_with_context() -> None:
    incoming = FakeIncoming()
    memory = FakeMemory(
        [
            ChatMessage(role="user", content="quanto foi de uber?"),
            ChatMessage(
                role="assistant",
                content=(
                    "Você gastou R$ 630,36 com uber de 01/10/2026 a "
                    "24/10/2026 (32 lançamentos)."
                ),
            ),
        ]
    )
    follow_up = HeuristicFollowUp(
        rewritten=(
            "quanto gastei com uber neste mês comparado ao mês passado?"
        )
    )
    conversation = TelegramConversation(
        incoming=incoming,  # type: ignore[arg-type]
        memory=memory,
        follow_up=follow_up,  # type: ignore[arg-type]
    )

    await conversation.respond(
        "chat", "isso é mais ou menos do que no mês passado?"
    )

    assert follow_up.calls == ["isso é mais ou menos do que no mês passado?"]
    assert incoming.calls == [
        "quanto gastei com uber neste mês comparado ao mês passado?"
    ]


async def test_without_history_the_message_is_not_rewritten() -> None:
    incoming = FakeIncoming()
    follow_up = FakeFollowUp()
    conversation = TelegramConversation(
        incoming=incoming,  # type: ignore[arg-type]
        follow_up=follow_up,  # type: ignore[arg-type]
    )

    await conversation.respond("chat", "e no cartão?")

    assert follow_up.calls == []
    assert incoming.calls == ["e no cartão?"]


async def test_provider_failure_is_explained() -> None:
    error = ProviderError("pluggy down")
    incoming = FakeIncoming(error=error)
    explainer = FakeExplainer("O banco não respondeu.")
    conversation = TelegramConversation(
        incoming=incoming,  # type: ignore[arg-type]
        explain_failure=explainer,  # type: ignore[arg-type]
    )

    answer = await conversation.respond("chat", "qual meu saldo")

    assert answer == "O banco não respondeu."
    assert explainer.calls == [("qual meu saldo", error)]


async def test_explainer_failure_falls_back_to_the_generic_reply() -> None:
    class FailingExplainer:
        async def execute(self, *, question: str, error: Exception) -> str:
            raise ProviderError("llm down")

    conversation = TelegramConversation(
        incoming=FakeIncoming(error=ProviderError("pluggy down")),  # type: ignore[arg-type]
        explain_failure=FailingExplainer(),  # type: ignore[arg-type]
    )

    answer = await conversation.respond("chat", "qual meu saldo")

    assert answer == "Não consegui concluir agora. Tente novamente."


async def test_renders_a_spending_answer() -> None:
    answer = SpendingAnswerMessage(
        start=date(2026, 10, 1),
        end=date(2026, 10, 20),
        label="Uber",
        total_cents=2500,
        count=1,
        category=None,
        keywords=("uber",),
    )
    conversation = TelegramConversation(
        incoming=FakeIncoming(answer)  # type: ignore[arg-type]
    )

    rendered = await conversation.respond("chat", "quanto gastei com uber?")

    assert "R$ 25,00" in rendered
