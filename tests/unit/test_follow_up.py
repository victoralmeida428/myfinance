"""Unit tests for the follow-up question resolver."""

from __future__ import annotations

from typing import Any

import pytest

from myfinance.application.errors import ProviderError
from myfinance.domain.models import ChatMessage
from myfinance.infrastructure.parsing.follow_up import OpenCodeFollowUpResolver

HISTORY = (
    ChatMessage(role="user", content="Quanto gastei com Uber?"),
    ChatMessage(role="assistant", content="Você gastou R$ 342,50 com Uber."),
)


class FakeLanguageModel:
    """Returns a canned completion, or raises a canned error."""

    def __init__(
        self, reply: str = "", *, error: Exception | None = None
    ) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[Any]] = []

    async def complete(
        self, messages: list[Any], *, session_id: str | None = None
    ) -> str:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.reply


def test_should_rewrite_accepts_short_or_elliptical_messages() -> None:
    resolver = OpenCodeFollowUpResolver(FakeLanguageModel())

    assert resolver.should_rewrite("e no cartão?") is True
    assert resolver.should_rewrite("no cartão?") is True
    assert resolver.should_rewrite("nesse mês?") is True
    assert resolver.should_rewrite("agora") is True


@pytest.mark.parametrize(
    "text",
    [
        "Resumo da semana",
        "qual meu saldo",
        "meu saldo",
        "me ajuda",
        "O que você pode fazer?",
        "gastei 45",
        "extrato de hoje",
        "meus gastos com uber",
        "onde posso cortar gastos?",
        "45",
        "quanto eu gastei com transporte na semana passada inteira?",
    ],
)
def test_should_not_rewrite_complete_requests(text: str) -> None:
    resolver = OpenCodeFollowUpResolver(FakeLanguageModel())

    assert resolver.should_rewrite(text) is False


async def test_rewrite_returns_the_model_answer() -> None:
    model = FakeLanguageModel("quanto gastei de uber no cartão em outubro?")
    resolver = OpenCodeFollowUpResolver(model)

    rewritten = await resolver.rewrite("e no cartão?", HISTORY)

    assert rewritten == "quanto gastei de uber no cartão em outubro?"


async def test_rewrite_includes_the_history_and_current_message_in_the_prompt() -> None:
    model = FakeLanguageModel("pergunta reescrita")
    resolver = OpenCodeFollowUpResolver(model)

    await resolver.rewrite("e no cartão?", HISTORY)

    prompt = model.calls[0][1].content
    assert "Usuário: Quanto gastei com Uber?" in prompt
    assert "Bot: Você gastou R$ 342,50 com Uber." in prompt
    assert "Mensagem atual: e no cartão?" in prompt


async def test_system_prompt_asks_for_standalone_brazilian_portuguese() -> None:
    model = FakeLanguageModel("pergunta reescrita")
    resolver = OpenCodeFollowUpResolver(model)

    await resolver.rewrite("e no cartão?", HISTORY)

    system_prompt = model.calls[0][0].content
    assert "pergunta independente" in system_prompt
    assert "português do Brasil" in system_prompt
    assert "Nunca invente valores" in system_prompt


async def test_blank_text_returns_none_without_calling_the_model() -> None:
    model = FakeLanguageModel("não deveria ser usado")
    resolver = OpenCodeFollowUpResolver(model)

    assert await resolver.rewrite("   ", HISTORY) is None
    assert model.calls == []


async def test_empty_history_returns_the_trimmed_text() -> None:
    model = FakeLanguageModel("não deveria ser usado")
    resolver = OpenCodeFollowUpResolver(model)

    assert await resolver.rewrite("  qual meu saldo?  ", ()) == "qual meu saldo?"
    assert model.calls == []


async def test_blank_model_answer_returns_none() -> None:
    resolver = OpenCodeFollowUpResolver(FakeLanguageModel("   "))

    assert await resolver.rewrite("e no cartão?", HISTORY) is None


async def test_provider_error_propagates() -> None:
    model = FakeLanguageModel(error=ProviderError("provider down"))
    resolver = OpenCodeFollowUpResolver(model)

    with pytest.raises(ProviderError):
        await resolver.rewrite("e no cartão?", HISTORY)
