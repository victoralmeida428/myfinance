"""Domain models: immutable value objects and entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from myfinance.domain.exceptions import InvalidClientUserId

__all__ = ["ChatMessage", "ClientUserId", "ConnectToken"]


@dataclass(frozen=True, slots=True)
class ClientUserId:
    """Identifier of a client user, as known by the payments provider."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value:
            raise InvalidClientUserId("client_user_id must not be empty.")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class ConnectToken:
    """Short-lived token used by the client to open the connect widget."""

    value: str = field(repr=False)

    def reveal(self) -> str:
        """Return the raw token; only presentation code should call this."""
        return self.value

    def __repr__(self) -> str:
        return "ConnectToken(***)"

    def __str__(self) -> str:
        return "***"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single message in a chat completion request."""

    role: Literal["system", "user", "assistant"]
    content: str

    def as_dict(self) -> dict[str, str]:
        """Render the message in the provider's wire format."""
        return {"role": self.role, "content": self.content}
