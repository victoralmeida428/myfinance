import pytest

from myfinance.application.use_cases import CreateConnectTokenUseCase
from myfinance.domain.exceptions import InvalidClientUserId
from myfinance.domain.models import ClientUserId, ConnectToken


class FakeConnectTokenProvider:
    def __init__(self) -> None:
        self.received: list[ClientUserId] = []

    async def create_connect_token(self, client_user_id: ClientUserId) -> ConnectToken:
        self.received.append(client_user_id)
        return ConnectToken("token-abc")


async def test_execute_returns_the_token_and_strips_the_id() -> None:
    provider = FakeConnectTokenProvider()
    use_case = CreateConnectTokenUseCase(provider)

    token = await use_case.execute("  user-42  ")

    assert token.reveal() == "token-abc"
    assert provider.received[0].value == "user-42"


async def test_blank_id_is_rejected_before_reaching_the_provider() -> None:
    provider = FakeConnectTokenProvider()
    use_case = CreateConnectTokenUseCase(provider)

    with pytest.raises(InvalidClientUserId):
        await use_case.execute("   ")

    assert provider.received == []


def test_connect_token_never_leaks_in_repr() -> None:
    token = ConnectToken("super-secret")

    assert "super-secret" not in repr(token)
    assert str(token) == "***"
