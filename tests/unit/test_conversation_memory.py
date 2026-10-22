"""Unit tests for the SQLite conversation memory adapter."""

from __future__ import annotations

from pathlib import Path

from myfinance.infrastructure.sqlite import (
    SqliteConversationMemory,
    SqliteDatabase,
)


def make_memory(tmp_path: Path) -> SqliteConversationMemory:
    return SqliteConversationMemory(SqliteDatabase(tmp_path / "memory.db"))


async def test_recent_returns_messages_in_chronological_order_per_chat(
    tmp_path: Path,
) -> None:
    memory = make_memory(tmp_path)
    await memory.append("chat-a", "user", "primeira")
    await memory.append("chat-a", "assistant", "resposta")
    await memory.append("chat-b", "user", "outra conversa")
    await memory.append("chat-a", "user", "segunda")

    history = await memory.recent("chat-a")

    assert [(message.role, message.content) for message in history] == [
        ("user", "primeira"),
        ("assistant", "resposta"),
        ("user", "segunda"),
    ]


async def test_recent_limits_the_history_to_the_last_five_exchanges(
    tmp_path: Path,
) -> None:
    memory = make_memory(tmp_path)
    for index in range(6):
        await memory.append("chat", "user", f"pergunta {index}")
        await memory.append("chat", "assistant", f"resposta {index}")

    history = await memory.recent("chat", exchanges=5)

    assert len(history) == 10
    expected = [
        ("user", f"pergunta {index}") if role == "user"
        else ("assistant", f"resposta {index}")
        for index in range(1, 6)
        for role in ("user", "assistant")
    ]
    assert [(message.role, message.content) for message in history] == expected


async def test_storage_keeps_only_the_last_ten_rows_per_chat(
    tmp_path: Path,
) -> None:
    memory = make_memory(tmp_path)
    for index in range(12):
        await memory.append("chat", "user", f"mensagem {index}")

    history = await memory.recent("chat", exchanges=100)

    assert [message.content for message in history] == [
        f"mensagem {index}" for index in range(2, 12)
    ]


async def test_clear_removes_only_the_requested_chat(tmp_path: Path) -> None:
    memory = make_memory(tmp_path)
    await memory.append("chat-a", "user", "a")
    await memory.append("chat-b", "user", "b")

    await memory.clear("chat-a")

    assert await memory.recent("chat-a") == ()
    assert [message.content for message in await memory.recent("chat-b")] == [
        "b"
    ]


async def test_recent_preserves_the_stored_role_and_content(tmp_path: Path) -> None:
    memory = make_memory(tmp_path)
    await memory.append("chat", "user", "e no cartão?")
    await memory.append("chat", "assistant", "Você gastou R$ 10,00.")

    history = await memory.recent("chat")

    assert history[0].role == "user"
    assert history[0].content == "e no cartão?"
    assert history[1].role == "assistant"
    assert history[1].content == "Você gastou R$ 10,00."
