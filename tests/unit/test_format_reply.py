"""Unit tests for the single reply renderer used by the conversation."""

from __future__ import annotations

from datetime import date

from myfinance.application.dto import (
    AccountsAnswer,
    HelpMessage,
    IncomeMessage,
    NeedsClarification,
    SummaryMessage,
)
from myfinance.domain.banking import BankAccount
from myfinance.domain.summary import build_period_summary
from myfinance.presentation.telegram.commands import HELP_TEXT
from myfinance.presentation.telegram.formatting import (
    format_banking,
    format_period_summary,
    format_reply,
)
from uuid import uuid4


def test_format_reply_renders_a_banking_answer() -> None:
    answer = AccountsAnswer(
        accounts=(
            BankAccount(
                id=uuid4(),
                item_id=uuid4(),
                type="BANK",
                name="Conta",
                balance_cents=100,
                currency="BRL",
                institution="Itaú",
            ),
        )
    )

    assert format_reply(answer) == format_banking(answer)


def test_format_reply_renders_a_period_summary() -> None:
    summary = build_period_summary(
        date(2026, 10, 1), date(2026, 10, 20), ()
    )

    assert format_reply(SummaryMessage(summary=summary)) == format_period_summary(
        summary
    )


def test_format_reply_renders_a_clarification() -> None:
    assert format_reply(NeedsClarification("tente de novo")) == "tente de novo"


def test_format_reply_renders_the_help_text() -> None:
    assert format_reply(HelpMessage()) == HELP_TEXT


def test_format_reply_explains_the_income_limitation() -> None:
    text = format_reply(IncomeMessage())

    assert "Ainda não acompanho receitas" in text
    assert "extrato de hoje" in text
