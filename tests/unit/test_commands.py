"""Unit tests for Telegram command parsing and help text."""

import pytest

from myfinance.presentation.telegram.commands import HELP_TEXT, parse_command


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/resumo", ("resumo", None)),
        ("/resumo ontem", ("resumo", "ontem")),
        ("/resumo@my_bot 25/10", ("resumo", "25/10")),
        ("/ajuda", ("ajuda", None)),
        ("/start", ("start", None)),
        ("/help", ("help", None)),
    ],
)
def test_parse_command_accepts_known_commands(
    text: str, expected: tuple[str, str | None]
) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize("text", ["texto", "/desconhecido", "/"])
def test_parse_command_rejects_non_commands(text: str) -> None:
    assert parse_command(text) is None


@pytest.mark.parametrize(
    "label",
    ["Alimentação", "Transporte", "Lazer", "Saúde", "Serviços", "Outros"],
)
def test_help_text_lists_every_category(label: str) -> None:
    assert label in HELP_TEXT


def test_help_text_documents_the_data_commands() -> None:
    assert "/resumo" in HELP_TEXT
    assert "/detalhes" in HELP_TEXT


@pytest.mark.parametrize(
    "phrase",
    [
        "quanto gastei com uber esse mês?",
        "meus gastos com uber",
        "quanto gastei com alimentos?",
        "quanto em posto de gasolina?",
        "qual meu saldo",
        "extrato de hoje",
        "qual foi o mês que eu mais gastei?",
        "onde posso cortar gastos?",
    ],
)
def test_help_text_documents_spending_questions(phrase: str) -> None:
    assert phrase in HELP_TEXT
