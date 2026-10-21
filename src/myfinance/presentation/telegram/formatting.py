"""Plain-text rendering of finance data for Telegram.

Every function here returns text without markup, emojis or ``parse_mode``
hints: the bot sends raw text so nothing depends on Telegram's HTML/Markdown
escaping rules.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from myfinance.application.dto import (
    AccountsAnswer,
    BankingAnswer,
    IdentityAnswer,
    NoPluggyItem,
    RegistrationResult,
    TopMonthMessage,
    TransactionsAnswer,
)
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.summary import (
    BalanceStatus,
    CategoryBalance,
    DailySummary,
    PeriodSummary,
)

__all__ = [
    "format_banking",
    "format_brl",
    "format_date",
    "format_details",
    "format_period_summary",
    "format_registration",
    "format_summary",
    "format_top_month",
    "mask_document",
]

_NO_PLUGGY_ITEM_REPLY = (
    "Nenhuma conta conectada. Conecte pelo Pluggy Connect e registre com "
    "/item <uuid>."
)
_NO_ACCOUNTS_REPLY = "Nenhuma conta encontrada."
_NO_TRANSACTIONS_REPLY = "Nenhuma transação no período."
_NO_IDENTITY_REPLY = "Dados do titular não disponíveis."
_NOT_INFORMED = "não informado"

_STATUS_TAGS: dict[BalanceStatus, str] = {
    BalanceStatus.OK: "[OK]",
    BalanceStatus.OVER: "[ESTOURO]",
    BalanceStatus.UNPLANNED: "[SEM PREVISÃO]",
}

_KIND_LABELS: dict[EntryKind, str] = {
    EntryKind.FORECAST: "PREVISÃO",
    EntryKind.EXPENSE: "DESPESA",
}

_MONTH_NAMES: tuple[str, ...] = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def format_brl(cents: int) -> str:
    """Render ``cents`` as Brazilian currency (``123456`` -> ``R$ 1.234,56``)."""
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def format_date(day: date) -> str:
    """Render ``day`` in the Brazilian ``DD/MM/YYYY`` format."""
    return f"{day:%d/%m/%Y}"


def mask_document(document: str | None) -> str:
    """Mask a document, revealing only the edges of an 11-digit CPF."""
    if document is None:
        return _NOT_INFORMED
    digits = re.sub(r"\D", "", document)
    if not digits:
        return _NOT_INFORMED
    if len(digits) == 11:
        return f"{digits[:3]}.***.***-{digits[-2:]}"
    return "***"


def format_banking(answer: BankingAnswer) -> str:
    """Render an answer to a natural-language banking question."""
    if isinstance(answer, NoPluggyItem):
        return _NO_PLUGGY_ITEM_REPLY
    if isinstance(answer, AccountsAnswer):
        return _format_accounts(answer)
    if isinstance(answer, TransactionsAnswer):
        return _format_transactions(answer)
    return _format_identity(answer)


def _format_accounts(answer: AccountsAnswer) -> str:
    if not answer.accounts:
        return _NO_ACCOUNTS_REPLY

    groups: dict[str, list[str]] = {}
    for account in answer.accounts:
        institution = account.institution or "Contas"
        groups.setdefault(institution, []).append(
            f"- {account.name} ({account.type}): "
            f"{format_brl(account.balance_cents)}"
        )

    blocks = [
        "\n".join((institution, *lines))
        for institution, lines in groups.items()
    ]
    return "\n\n".join(blocks)


def _format_transactions(answer: TransactionsAnswer) -> str:
    start = format_date(answer.start)
    if answer.start == answer.end:
        header = f"Extrato de {start}"
    else:
        header = f"Extrato de {start} a {format_date(answer.end)}"

    if not answer.transactions:
        return _NO_TRANSACTIONS_REPLY

    lines = [header]
    for transaction in answer.transactions:
        lines.append(
            f"- {transaction.day:%d/%m} {transaction.description}: "
            f"{format_brl(transaction.amount_cents)}"
        )
    return "\n".join(lines)


def _format_identity(answer: IdentityAnswer) -> str:
    identity = answer.identity
    if identity is None:
        return _NO_IDENTITY_REPLY
    return "\n".join(
        (
            f"Titular: {identity.full_name or _NOT_INFORMED}",
            f"Documento: {mask_document(identity.document)}",
        )
    )


def format_registration(result: RegistrationResult) -> str:
    """Render the confirmation of a freshly registered entry."""
    entry = result.entry
    category = entry.category
    amount = format_brl(entry.amount.cents)
    day = format_date(entry.day)

    if entry.kind is EntryKind.FORECAST:
        lines = [f"Previsão registrada: {amount} em {category.label} para {day}."]
    else:
        lines = [f"Despesa registrada: {amount} em {category.label} para {day}."]

    balance = _balance_for(result.summary, category)
    if balance is None:
        return "\n".join(lines)

    if entry.kind is EntryKind.FORECAST:
        lines.append(
            f"Teto de {category.label} no dia: "
            f"{format_brl(balance.forecast_cents)}."
        )

    if balance.status is BalanceStatus.OVER:
        lines.append(
            f"Atenção: estourou a previsão de {category.label} "
            f"(previsto {format_brl(balance.forecast_cents)}, "
            f"realizado {format_brl(balance.expense_cents)})."
        )
    elif balance.status is BalanceStatus.UNPLANNED:
        lines.append(
            f"Atenção: gasto sem previsão em {category.label} "
            f"({format_brl(balance.expense_cents)})."
        )
    return "\n".join(lines)


def format_summary(summary: DailySummary) -> str:
    """Render a day's forecast/expense reconciliation."""
    day = format_date(summary.day)
    if not summary.balances:
        return f"Nenhum lançamento em {day}."

    blocks = [f"Resumo de {day}", *_render_balances(summary)]
    return "\n\n".join(blocks)


def format_period_summary(summary: PeriodSummary) -> str:
    """Render a period's forecast/expense reconciliation."""
    start = format_date(summary.start)
    end = format_date(summary.end)
    if not summary.balances:
        return f"Nenhum lançamento de {start} a {end}."

    blocks = [f"Resumo de {start} a {end}", *_render_balances(summary)]
    return "\n\n".join(blocks)


def _render_balances(summary: DailySummary | PeriodSummary) -> list[str]:
    """Render the category blocks, surprises, totals and status of a summary."""
    blocks: list[str] = []
    for balance in summary.balances:
        category = balance.category.label
        if balance.bank_expense_cents > 0:
            realized = (
                f"Realizado: {format_brl(balance.expense_cents)} "
                f"(banco {format_brl(balance.bank_expense_cents)} + "
                f"manual {format_brl(balance.manual_expense_cents)})"
            )
        else:
            realized = f"Realizado: {format_brl(balance.expense_cents)}"
        blocks.append(
            "\n".join(
                (
                    f"{category} {_STATUS_TAGS[balance.status]}",
                    f"Previsto: {format_brl(balance.forecast_cents)}",
                    realized,
                    f"Saldo: {format_brl(balance.difference_cents)}",
                )
            )
        )

    surprises = [
        balance
        for balance in summary.balances
        if balance.status is BalanceStatus.UNPLANNED
    ]
    if surprises:
        listed = "; ".join(
            f"{balance.category.label} {format_brl(balance.expense_cents)}"
            for balance in surprises
        )
        blocks.append(f"Sem previsão: {listed}")

    blocks.append(
        f"Total: previsto {format_brl(summary.total_forecast_cents)} | "
        f"realizado {format_brl(summary.total_expense_cents)} | "
        f"saldo {format_brl(summary.total_difference_cents)}"
    )

    if summary.has_deficit:
        deficit = abs(summary.total_difference_cents)
        blocks.append(f"Status: déficit de {format_brl(deficit)}")
    else:
        blocks.append("Status: dentro da meta")

    return blocks


def format_top_month(message: TopMonthMessage) -> str:
    """Render the month with the highest realized spending."""
    if not message.ranking:
        return "Nenhum gasto encontrado nos últimos 12 meses."

    winner = message.ranking[0]
    month_label = f"{_MONTH_NAMES[winner.month - 1]}/{winner.year}"
    headline = (
        f"O mês em que você mais gastou foi {month_label}: "
        f"{format_brl(winner.expense_cents)}."
    )
    if (
        winner.year == message.window_end.year
        and winner.month == message.window_end.month
    ):
        headline += " (mês atual, parcial)"

    blocks = [headline]
    ranking_lines = ["Top 3:"]
    for position, month in enumerate(message.ranking, start=1):
        ranking_lines.append(
            f"{position}. {_MONTH_NAMES[month.month - 1]}/{month.year} — "
            f"{format_brl(month.expense_cents)}"
        )
    blocks.append("\n".join(ranking_lines))

    category_lines = [f"Categorias em {month_label}:"]
    for balance in message.winner_balances:
        if balance.expense_cents <= 0:
            continue
        line = (
            f"- {balance.category.label}: "
            f"{format_brl(balance.expense_cents)}"
        )
        if balance.bank_expense_cents > 0:
            line += (
                f" (banco {format_brl(balance.bank_expense_cents)} + "
                f"manual {format_brl(balance.manual_expense_cents)})"
            )
        category_lines.append(line)
    if len(category_lines) > 1:
        blocks.append("\n".join(category_lines))

    return "\n\n".join(blocks)


def format_details(entries: Sequence[Entry], day: date) -> str:
    """Render every entry of ``day`` as one line each."""
    if not entries:
        return f"Nenhum lançamento em {format_date(day)}."

    lines = [f"Lançamentos de {format_date(day)}"]
    for entry in entries:
        description = " ".join(entry.description.split())
        lines.append(
            f"{_KIND_LABELS[entry.kind]} | {entry.category.label} | "
            f"{format_brl(entry.amount.cents)} | {description} "
            f"({entry.created_at:%H:%M})"
        )
    return "\n".join(lines)


def _balance_for(
    summary: DailySummary, category: Category
) -> CategoryBalance | None:
    """Return the balance of ``category`` in ``summary``, when present."""
    for balance in summary.balances:
        if balance.category == category:
            return balance
    return None
