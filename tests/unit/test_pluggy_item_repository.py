"""Regression tests for the Pluggy item repository upsert."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from myfinance.domain.banking import PluggyItem
from myfinance.infrastructure.sqlite import (
    SqliteDatabase,
    SqlitePluggyItemRepository,
)

CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
RENAMED_AT = datetime(2026, 10, 20, 11, 0, tzinfo=UTC)


def _count_rows(database: SqliteDatabase) -> int:
    with closing(database.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM pluggy_items"
        ).fetchone()[0]


async def test_upsert_without_connector_name_preserves_the_stored_name(
    tmp_path: Path,
) -> None:
    database = SqliteDatabase(tmp_path / "items.db")
    repository = SqlitePluggyItemRepository(database)
    item_id = uuid4()

    await repository.upsert(
        PluggyItem(
            id=item_id,
            status="created",
            error=None,
            updated_at=CREATED_AT,
            connector_name="MeuPluggy",
        )
    )
    active = await repository.list_active()
    assert len(active) == 1
    assert active[0].id == item_id
    assert active[0].connector_name == "MeuPluggy"

    await repository.upsert(
        PluggyItem(
            id=item_id,
            status="updated",
            error=None,
            updated_at=UPDATED_AT,
            connector_name=None,
        )
    )
    active = await repository.list_active()
    assert len(active) == 1
    assert active[0].connector_name == "MeuPluggy"
    assert active[0].status == "updated"
    assert active[0].error is None
    assert active[0].updated_at == UPDATED_AT

    await repository.upsert(
        PluggyItem(
            id=item_id,
            status="updated",
            error="boom",
            updated_at=RENAMED_AT,
            connector_name="Nubank",
        )
    )
    active = await repository.list_active()
    assert len(active) == 1
    assert active[0].connector_name == "Nubank"
    assert active[0].status == "updated"
    assert active[0].error == "boom"
    assert active[0].updated_at == RENAMED_AT
    assert _count_rows(database) == 1
