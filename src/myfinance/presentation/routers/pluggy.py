"""Pluggy item registration and webhook endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from myfinance.application.use_cases import RegisterPluggyItemUseCase
from myfinance.config import Settings, get_settings
from myfinance.presentation.dependencies import (
    get_register_pluggy_item_use_case,
)
from myfinance.presentation.schemas import (
    PluggyItemRequest,
    PluggyItemResponse,
    PluggyWebhookPayload,
)

router = APIRouter(prefix="/api", tags=["pluggy"])

_EVENT_STATUSES = {
    "item/created": "created",
    "item/updated": "updated",
    "item/error": "error",
}

_IGNORED_RESPONSE = {"received": True, "ignored": True}


@router.post("/pluggy/items", response_model=PluggyItemResponse)
async def register_pluggy_item(
    payload: PluggyItemRequest,
    use_case: Annotated[
        RegisterPluggyItemUseCase,
        Depends(get_register_pluggy_item_use_case),
    ],
) -> PluggyItemResponse:
    """Persist the item linked in the browser."""
    item = await use_case.execute(
        payload.item_id,
        status="created",
        connector_name=payload.connector_name,
    )
    return PluggyItemResponse(item_id=item.id, status=item.status)


@router.post("/webhooks/pluggy")
async def receive_pluggy_webhook(
    payload: PluggyWebhookPayload,
    settings: Annotated[Settings, Depends(get_settings)],
    use_case: Annotated[
        RegisterPluggyItemUseCase,
        Depends(get_register_pluggy_item_use_case),
    ],
    x_webhook_token: Annotated[str | None, Header(alias="X-Webhook-Token")] = None,
) -> dict[str, bool]:
    """Store the latest state of an item without calling Pluggy."""
    secret = settings.pluggy_webhook_secret
    if secret is not None and secret.get_secret_value() != x_webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    status = _EVENT_STATUSES.get(payload.event)
    if status is None or payload.item_id is None:
        return dict(_IGNORED_RESPONSE)

    error = str(payload.error) if payload.error is not None else None
    await use_case.execute(payload.item_id, status=status, error=error)
    return {"received": True}
