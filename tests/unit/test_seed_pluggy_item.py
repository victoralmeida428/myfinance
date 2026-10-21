"""Tests for seeding the configured Pluggy item when the bot starts."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from myfinance.config import Settings
from myfinance.presentation.telegram.app import seed_configured_item


@dataclass
class _FakeRegisterItem:
    calls: list[tuple[UUID, str | None]] = field(default_factory=list)

    async def execute(
        self,
        item_id: UUID,
        *,
        status: str = "created",
        error: str | None = None,
        connector_name: str | None = None,
    ) -> None:
        self.calls.append((item_id, connector_name))


@dataclass
class _FakeContainer:
    register_item: _FakeRegisterItem = field(default_factory=_FakeRegisterItem)


def test_seed_registers_configured_item() -> None:
    item_id = uuid4()
    settings = Settings(
        _env_file=None,
        pluggy_item_id=item_id,
        pluggy_connector_name="MeuPluggy",
    )
    container = _FakeContainer()

    seed_configured_item(settings, container)  # type: ignore[arg-type]

    assert container.register_item.calls == [(item_id, "MeuPluggy")]


def test_seed_does_nothing_without_item_id() -> None:
    settings = Settings(_env_file=None)
    container = _FakeContainer()

    seed_configured_item(settings, container)  # type: ignore[arg-type]

    assert container.register_item.calls == []


def test_seed_passes_none_connector_name() -> None:
    item_id = uuid4()
    settings = Settings(_env_file=None, pluggy_item_id=item_id)
    container = _FakeContainer()

    seed_configured_item(settings, container)  # type: ignore[arg-type]

    assert container.register_item.calls == [(item_id, None)]
