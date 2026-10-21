"""Unit tests for Telegram text rendering."""

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.application.dto import RegistrationResult
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import build_daily_summary
from myfinance.presentation.telegram.formatting import (
    format_brl,
    format_date,
    format_details,
    format_registration,
    format_summary,
)

DAY = date(2026, 10, 20)
CREATED_AT = datetime(2026, 10, 20, 9, 5, tzinfo=UTC)


def make_entry(
    kind: EntryKind,
    cents: int,
    category: Category = Category.ALIMENTACAO,
    *,
    description: str = "lançamento",
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=DAY,
        amount=Money(cents),
        description=description,
        category=category,
        created_at=CREATED_AT,
    )


def test_format_brl_renders_thousands_and_cents() -> None:
    assert format_brl(123456) == "R$ 1.234,56"


def test_format_brl_renders_negative_amounts() -> None:
    assert format_brl(-123456) == "-R$ 1.234,56"


def test_format_brl_renders_zero() -> None:
    assert format_brl(0) == "R$ 0,00"


def test_format_date_uses_brazilian_order() -> None:
    assert format_date(DAY) == "20/10/2026"


def test_format_registration_for_a_forecast_shows_the_ceiling() -> None:
    entry = make_entry(EntryKind.FORECAST, 8000)
    result = RegistrationResult(
        entry=entry, summary=build_daily_summary(DAY, [entry])
    )

    text = format_registration(result)

    assert "Previsão registrada" in text
    assert "Teto de" in text


def test_format_registration_for_an_expense() -> None:
    entry = make_entry(EntryKind.EXPENSE, 4500)
    result = RegistrationResult(
        entry=entry, summary=build_daily_summary(DAY, [entry])
    )

    text = format_registration(result)

    assert "Despesa registrada" in text


def test_format_registration_reports_an_over_budget_expense() -> None:
    forecast = make_entry(EntryKind.FORECAST, 3000)
    expense = make_entry(EntryKind.EXPENSE, 4500)
    result = RegistrationResult(
        entry=expense, summary=build_daily_summary(DAY, [forecast, expense])
    )

    text = format_registration(result)

    assert "estourou a previsão" in text


def test_format_registration_reports_an_unplanned_expense() -> None:
    entry = make_entry(EntryKind.EXPENSE, 6000, Category.LAZER)
    result = RegistrationResult(
        entry=entry, summary=build_daily_summary(DAY, [entry])
    )

    text = format_registration(result)

    assert "gasto sem previsão" in text


def test_format_summary_includes_status_tags_and_totals() -> None:
    entries = [
        make_entry(EntryKind.FORECAST, 8000, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 4500, Category.ALIMENTACAO),
        make_entry(EntryKind.FORECAST, 2000, Category.TRANSPORTE),
        make_entry(EntryKind.EXPENSE, 2500, Category.TRANSPORTE),
        make_entry(EntryKind.EXPENSE, 1000, Category.LAZER),
    ]

    text = format_summary(build_daily_summary(DAY, entries))

    assert "Resumo de" in text
    assert "[OK]" in text
    assert "[ESTOURO]" in text
    assert "[SEM PREVISÃO]" in text
    assert "Sem previsão:" in text
    assert "Total: previsto" in text
    assert "Status: dentro da meta" in text


def test_format_summary_reports_a_deficit() -> None:
    entries = [
        make_entry(EntryKind.FORECAST, 3000, Category.ALIMENTACAO),
        make_entry(EntryKind.EXPENSE, 5000, Category.ALIMENTACAO),
    ]

    text = format_summary(build_daily_summary(DAY, entries))

    assert "Status: déficit" in text


def test_format_summary_for_an_empty_day() -> None:
    text = format_summary(build_daily_summary(DAY, []))

    assert "Nenhum lançamento em" in text


def test_format_details_lists_kinds_and_times() -> None:
    entries = [
        make_entry(EntryKind.FORECAST, 8000, description="mercado"),
        make_entry(EntryKind.EXPENSE, 4500, description="almoço"),
    ]

    text = format_details(entries, DAY)

    assert "PREVISÃO" in text
    assert "DESPESA" in text
    assert "09:05" in text


def test_format_details_for_an_empty_day() -> None:
    text = format_details([], DAY)

    assert "Nenhum lançamento em" in text


def test_format_summary_breaks_the_realized_amount_into_bank_and_manual() -> None:
    forecast = make_entry(EntryKind.FORECAST, 8000)
    manual = make_entry(EntryKind.EXPENSE, 2000, Category.TRANSPORTE)
    bank = BankExpense(
        id=uuid4(),
        day=DAY,
        description="compra",
        amount_cents=3000,
        category=Category.TRANSPORTE,
        institution="Nubank",
    )

    text = format_summary(
        build_daily_summary(DAY, [forecast, manual], [bank])
    )

    assert (
        "Realizado: R$ 50,00 (banco R$ 30,00 + manual R$ 20,00)" in text
    )


def test_format_summary_keeps_the_manual_only_realized_amount_unchanged() -> None:
    forecast = make_entry(EntryKind.FORECAST, 8000)
    manual = make_entry(EntryKind.EXPENSE, 4500)

    text = format_summary(build_daily_summary(DAY, [forecast, manual]))

    assert "Realizado: R$ 45,00" in text
    assert "(banco" not in text
