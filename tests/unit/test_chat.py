from myfinance.application.use_cases import ChatUseCase
from myfinance.domain.models import ChatMessage


class FakeLanguageModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[ChatMessage], str | None]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str:
        self.calls.append((list(messages), session_id))
        return "ok"


async def test_chat_forwards_messages_and_session() -> None:
    model = FakeLanguageModel()
    use_case = ChatUseCase(model)
    messages = [ChatMessage(role="user", content="oi")]

    answer = await use_case.execute(messages, session_id="sess-1")

    assert answer == "ok"
    assert model.calls[0][0][0].content == "oi"
    assert model.calls[0][1] == "sess-1"
