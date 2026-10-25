"""Bot command parsing and the user-facing help text."""

from __future__ import annotations

__all__ = ["HELP_TEXT", "parse_command"]

_COMMANDS = frozenset({"start", "ajuda", "help", "resumo", "detalhes"})

HELP_TEXT = """Olá! Eu registro previsões e despesas do seu dia.

Comandos:
/start - começar
/ajuda (ou /help) - mostrar esta ajuda
/resumo [data] - resumo do dia
/detalhes [data] - lançamentos do dia

A data é opcional: hoje, ontem, amanhã, 2026-10-25 ou 25/10.

Exemplos:
"almoço hoje 45"
"previsão de transporte amanhã 30"
"farmácia ontem 120"

Perguntas de gasto:
"quanto gastei com uber esse mês?"
"meus gastos com uber"
"quanto gastei com alimentos?"
"quanto em posto de gasolina?"

Também respondo:
"qual meu saldo"
"extrato de hoje"
"qual foi o mês que eu mais gastei?"
"onde posso cortar gastos?"
"lançamentos do mês de set/2026"

Ainda não acompanho receitas; para o que entrou na conta, peça "extrato de hoje".

Categorias: Alimentação, Transporte, Lazer, Saúde, Serviços, Outros."""


def parse_command(text: str) -> tuple[str, str | None] | None:
    """Split a bot command into its lowercase name and raw argument.

    Accepts both ``/resumo ontem`` and the group-chat form
    ``/resumo@my_bot ontem``. Returns ``None`` when ``text`` is not a command
    this bot knows; the argument is ``None`` when nothing follows the command.
    Dates are deliberately not resolved here.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    parts = stripped[1:].split(maxsplit=1)
    if not parts:
        return None

    name = parts[0].split("@", 1)[0].lower()
    if name not in _COMMANDS:
        return None

    argument = parts[1].strip() if len(parts) > 1 else ""
    return name, argument or None
