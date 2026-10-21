"""HTTP-level tests for the Pluggy item and webhook endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from myfinance.config import Settings, get_settings
from myfinance.domain.banking import PluggyItem
from myfinance.presentation.dependencies import get_register_pluggy_item_use_case
from myfinance.presentation.routers import pluggy


class FakeRegisterPluggyItemUseCase:
    """Records every call and returns a deterministic item."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        item_id: UUID,
        *,
        status: str = "created",
        error: str | None = None,
        connector_name: str | None = None,
    ) -> PluggyItem:
        self.calls.append(
            {
                "item_id": item_id,
                "status": status,
                "error": error,
                "connector_name": connector_name,
            }
        )
        return PluggyItem(
            id=item_id,
            status=status,
            error=error,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            connector_name=connector_name,
        )


def _client(
    *,
    webhook_secret: str | None = None,
) -> tuple[TestClient, FakeRegisterPluggyItemUseCase]:
    app = FastAPI()
    app.include_router(pluggy.router)
    use_case = FakeRegisterPluggyItemUseCase()
    app.dependency_overrides[get_register_pluggy_item_use_case] = lambda: use_case
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        pluggy_webhook_secret=webhook_secret,
    )
    return TestClient(app), use_case


def test_register_item_stores_the_uuid_and_connector_name() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post(
        "/api/pluggy/items",
        json={"itemId": str(item_id), "connectorName": "Banco Teste"},
    )

    assert response.status_code == 200
    assert response.json() == {"itemId": str(item_id), "status": "created"}
    assert use_case.calls == [
        {
            "item_id": item_id,
            "status": "created",
            "error": None,
            "connector_name": "Banco Teste",
        }
    ]


def test_register_item_without_connector_name() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post("/api/pluggy/items", json={"itemId": str(item_id)})

    assert response.status_code == 200
    assert use_case.calls[0]["connector_name"] is None


def test_webhook_item_created_maps_to_created() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/created", "eventId": "evt-1", "itemId": str(item_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert use_case.calls == [
        {
            "item_id": item_id,
            "status": "created",
            "error": None,
            "connector_name": None,
        }
    ]


def test_webhook_item_updated_maps_to_updated() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "itemId": str(item_id)},
    )

    assert response.status_code == 200
    assert use_case.calls[0]["status"] == "updated"
    assert use_case.calls[0]["error"] is None


def test_webhook_item_error_maps_to_error_with_stringified_error() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post(
        "/api/webhooks/pluggy",
        json={
            "event": "item/error",
            "itemId": str(item_id),
            "error": {"code": "LOGIN_ERROR", "message": "invalid credentials"},
        },
    )

    assert response.status_code == 200
    assert use_case.calls[0]["status"] == "error"
    error = use_case.calls[0]["error"]
    assert isinstance(error, str)
    assert "LOGIN_ERROR" in error


def test_webhook_unknown_event_is_ignored() -> None:
    client, use_case = _client()
    item_id = uuid4()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/deleted", "itemId": str(item_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "ignored": True}
    assert use_case.calls == []


def test_webhook_missing_item_id_is_ignored() -> None:
    client, use_case = _client()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "eventId": "evt-2"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "ignored": True}
    assert use_case.calls == []


def test_webhook_without_configured_secret_needs_no_header() -> None:
    client, _ = _client()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "itemId": str(uuid4())},
    )

    assert response.status_code == 200


def test_webhook_rejects_missing_token_when_secret_configured() -> None:
    client, use_case = _client(webhook_secret="secret")

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "itemId": str(uuid4())},
    )

    assert response.status_code == 401
    assert use_case.calls == []


def test_webhook_rejects_wrong_token_when_secret_configured() -> None:
    client, use_case = _client(webhook_secret="secret")

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "itemId": str(uuid4())},
        headers={"X-Webhook-Token": "wrong"},
    )

    assert response.status_code == 401
    assert use_case.calls == []


def test_webhook_accepts_correct_token_when_secret_configured() -> None:
    client, use_case = _client(webhook_secret="secret")
    item_id = uuid4()

    response = client.post(
        "/api/webhooks/pluggy",
        json={"event": "item/updated", "itemId": str(item_id)},
        headers={"X-Webhook-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert use_case.calls[0]["item_id"] == item_id
