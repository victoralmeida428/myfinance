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
    ChatReply,
    HelpMessage,
    IdentityAnswer,
    NeedsClarification,
    NoPluggyItem,
    RegisteredMessage,
    RegistrationResult,
    SpendingAnswerMessage,
    SpendingPlanMessage,
    SummaryMessage,
    TopMonthMessage,
    TransactionsAnswer,
)
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.presentation.telegram.commands import HELP_TEXT
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
    "format_reply",
    "format_spending_answer",
    "format_spending_plan",
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


def format_reply(reply: ChatReply) -> str:
    """Render any reply produced by the conversation flow."""
    if isinstance(
        reply, (AccountsAnswer, TransactionsAnswer, IdentityAnswer, NoPluggyItem)
    ):
        return format_banking(reply)
    if isinstance(reply, RegisteredMessage):
        return format_registration(reply.result)
    if isinstance(reply, SummaryMessage):
        if isinstance(reply.summary, PeriodSummary):
            return format_period_summary(reply.summary)
        return format_summary(reply.summary)
    if isinstance(reply, TopMonthMessage):
        return format_top_month(reply)
    if isinstance(reply, SpendingAnswerMessage):
        return format_spending_answer(reply)
    if isinstance(reply, SpendingPlanMessage):
        return format_spending_plan(reply)
    if isinstance(reply, NeedsClarification):
        return reply.reason
    if isinstance(reply, HelpMessage):
        return HELP_TEXT
    raise TypeError(f"Unsupported reply: {type(reply).__name__}")


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


def format_spending_answer(message: SpendingAnswerMessage) -> str:
    """Render the answer to a free-form spending question."""
    if message.start == message.end:
        period = f"em {format_date(message.start)}"
    else:
        period = (
            f"de {format_date(message.start)} a {format_date(message.end)}"
        )

    if message.count == 0:
        return f"Nenhum gasto com {message.label} {period}."

    noun = "lançamento" if message.count == 1 else "lançamentos"
    return (
        f"Você gastou {format_brl(message.total_cents)} com "
        f"{message.label} {period} ({message.count} {noun})."
    )


def format_spending_plan(plan: SpendingPlanMessage) -> str:
    """Render a grounded savings plan from its computed numbers only."""
    if plan.start.year == plan.end.year and plan.start.month == plan.end.month:
        header = (
            f"Plano de gastos de "
            f"{_MONTH_NAMES[plan.start.month - 1]}/{plan.start.year}"
        )
    else:
        header = (
            f"Plano de gastos de {format_date(plan.start)} a "
            f"{format_date(plan.end)}"
        )

    if plan.count == 0:
        blocks = [header, "Nenhum gasto no período analisado."]
        if plan.narrative:
            blocks.append(plan.narrative)
        return "\n\n".join(blocks)

    noun = "lançamento" if plan.count == 1 else "lançamentos"
    total_line = f"Total: {format_brl(plan.total_cents)} ({plan.count} {noun})"
    if plan.previous_total_cents > 0:
        overall_delta = round(
            (plan.total_cents - plan.previous_total_cents)
            * 100
            / plan.previous_total_cents
        )
        total_line += (
            f" | {_format_delta(overall_delta)} vs período anterior "
            f"({format_brl(plan.previous_total_cents)})"
        )

    blocks = [f"{header}\n{total_line}"]

    if plan.categories:
        category_lines = ["Top categorias:"]
        for category in plan.categories[:3]:
            detail = (
                f"{category.category.label}: "
                f"{format_brl(category.total_cents)} "
                f"({category.share_percent}% do total, "
            )
            if category.delta_percent is None:
                detail += "sem base anterior)"
            else:
                detail += (
                    f"{_format_delta(category.delta_percent)} "
                    "vs período anterior)"
                )
            category_lines.append(f"- {detail}")
        blocks.append("\n".join(category_lines))

    if plan.cuts:
        cut_lines = ["Cortes sugeridos:"]
        for cut in plan.cuts[:3]:
            cut_lines.append(
                f"- {cut.label}: {format_brl(cut.cut_cents)} de "
                f"{format_brl(cut.current_cents)}"
            )
        blocks.append("\n".join(cut_lines))

    blocks.append(f"Meta de economia: {format_brl(plan.target_cents)}")
    if plan.narrative:
        blocks.append(plan.narrative)
    return "\n\n".join(blocks)


def _format_delta(delta_percent: int) -> str:
    """Render a signed percentage, keeping zero unsigned."""
    if delta_percent > 0:
        return f"+{delta_percent}%"
    return f"{delta_percent}%"


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
