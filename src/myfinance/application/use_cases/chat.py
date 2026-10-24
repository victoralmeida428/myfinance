"""Chat, error explanation and connect-token use cases."""

from __future__ import annotations

from collections.abc import Sequence

from myfinance.application.errors import ProviderError
from myfinance.application.ports import ConnectTokenProvider, LanguageModel
from myfinance.application.use_cases.common import run_with_timeout
from myfinance.domain.models import ChatMessage, ClientUserId, ConnectToken

__all__ = [
    "ChatUseCase",
    "CreateConnectTokenUseCase",
    "ExplainFailureUseCase",
]

_EXPLANATION_TIMEOUT_SECONDS = 15

_EXPLANATION_SYSTEM_PROMPT = (
    "Você é um assistente financeiro pessoal. Responda em português do "
    "Brasil, em no máximo três frases. Diga que não foi possível concluir o "
    "pedido, explique a causa em linguagem simples, repita brevemente o que "
    "a pessoa pediu e sugira tentar novamente. Nunca invente valores ou "
    "lançamentos e nunca exponha tokens, URLs ou detalhes técnicos."
)


class CreateConnectTokenUseCase:
    """Validate the client user id and obtain a connect token."""

    def __init__(self, provider: ConnectTokenProvider) -> None:
        self._provider = provider

    async def execute(self, client_user_id: str) -> ConnectToken:
        return await self._provider.create_connect_token(
            ClientUserId(client_user_id)
        )


class ChatUseCase:
    """Complete a chat conversation through a language model."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def execute(
        self,
        messages: Sequence[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str:
        return await self._model.complete(messages, session_id=session_id)


class ExplainFailureUseCase:
    """Ask the language model to explain a failed request in plain Portuguese."""

    def __init__(
        self,
        model: LanguageModel,
        *,
        timeout_seconds: float = _EXPLANATION_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def execute(self, *, question: str, error: Exception) -> str:
        messages = (
            ChatMessage(role="system", content=_EXPLANATION_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"Pedido do usuário: {question}\n"
                    f"Falha: {type(error).__name__}: {error}"
                ),
            ),
        )
        text = await run_with_timeout(
            self._model.complete(messages),
            self._timeout_seconds,
            "A explicação do erro demorou demais.",
        )
        explanation = text.strip()
        if not explanation:
            raise ProviderError("O modelo não explicou a falha.")
        return explanation
