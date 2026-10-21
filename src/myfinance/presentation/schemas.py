"""HTTP request and response schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConnectTokenRequest(BaseModel):
    """Body accepted by the connect-token endpoint."""

    client_user_id: str = Field(alias="clientUserId", min_length=1)


class ConnectTokenResponse(BaseModel):
    """Short-lived token handed to the browser."""

    access_token: str = Field(alias="accessToken")

    model_config = ConfigDict(populate_by_name=True)


class PluggyItemRequest(BaseModel):
    """Body sent by the frontend once a Pluggy item is linked."""

    item_id: UUID = Field(alias="itemId")
    connector_name: str | None = Field(default=None, alias="connectorName")

    model_config = ConfigDict(populate_by_name=True)


class PluggyItemResponse(BaseModel):
    """Confirmation that the item state was stored."""

    item_id: UUID = Field(alias="itemId")
    status: str

    model_config = ConfigDict(populate_by_name=True)


class PluggyWebhookPayload(BaseModel):
    """Event delivered by the Pluggy webhook."""

    event: str
    event_id: str | None = Field(default=None, alias="eventId")
    item_id: UUID | None = Field(default=None, alias="itemId")
    error: object | None = None

    model_config = ConfigDict(populate_by_name=True)
