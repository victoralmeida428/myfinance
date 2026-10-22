"""Unit tests for Telegram text rendering."""

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.application.dto import (
    CategoryPlan,
    CutSuggestion,
    MerchantSpend,
    RegistrationResult,
    SpendingAnswerMessage,
    SpendingPlanMessage,
)
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
    format_spending_answer,
    format_spending_plan,
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


def make_spending_answer(
    *,
    start: date = date(2026, 10, 1),
    end: date = date(2026, 10, 22),
    label: str = "Uber",
    total_cents: int = 34250,
    count: int = 12,
) -> SpendingAnswerMessage:
    return SpendingAnswerMessage(
        start=start,
        end=end,
        label=label,
        total_cents=total_cents,
        count=count,
        category=None,
        keywords=("uber",),
    )


def test_format_spending_answer_for_a_single_match() -> None:
    text = format_spending_answer(
        make_spending_answer(total_cents=3425, count=1)
    )

    assert text == (
        "Você gastou R$ 34,25 com Uber de 01/10/2026 a 22/10/2026 "
        "(1 lançamento)."
    )


def test_format_spending_answer_for_multiple_matches() -> None:
    text = format_spending_answer(make_spending_answer())

    assert text == (
        "Você gastou R$ 342,50 com Uber de 01/10/2026 a 22/10/2026 "
        "(12 lançamentos)."
    )


def test_format_spending_answer_for_zero_matches() -> None:
    text = format_spending_answer(
        make_spending_answer(total_cents=0, count=0)
    )

    assert text == "Nenhum gasto com Uber de 01/10/2026 a 22/10/2026."


def test_format_spending_answer_for_a_same_day_range() -> None:
    day = date(2026, 10, 22)
    text = format_spending_answer(
        make_spending_answer(
            start=day, end=day, total_cents=9000, count=3
        )
    )

    assert text == (
        "Você gastou R$ 90,00 com Uber em 22/10/2026 (3 lançamentos)."
    )


def make_spending_plan(
    *, narrative: str | None = None, count: int = 7
) -> SpendingPlanMessage:
    return SpendingPlanMessage(
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        total_cents=49000 if count else 0,
        count=count,
        previous_total_cents=32000 if count else 0,
        categories=(
            (
                CategoryPlan(
                    category=Category.TRANSPORTE,
                    total_cents=20000,
                    share_percent=41,
                    previous_cents=10000,
                    delta_percent=100,
                ),
                CategoryPlan(
                    category=Category.ALIMENTACAO,
                    total_cents=15000,
                    share_percent=31,
                    previous_cents=8000,
                    delta_percent=88,
                ),
                CategoryPlan(
                    category=Category.LAZER,
                    total_cents=5000,
                    share_percent=10,
                    previous_cents=5000,
                    delta_percent=0,
                ),
            )
            if count
            else ()
        ),
        merchants=(
            MerchantSpend(
                name="drogaria nova valqueir", total_cents=15000, count=2
            ),
        )
        if count
        else (),
        target_cents=4900 if count else 0,
        cuts=(
            (
                CutSuggestion(
                    label="Transporte", current_cents=20000, cut_cents=2450
                ),
                CutSuggestion(
                    label="Alimentação", current_cents=15000, cut_cents=1838
                ),
                CutSuggestion(
                    label="Lazer", current_cents=5000, cut_cents=612
                ),
            )
            if count
            else ()
        ),
        narrative=narrative,
    )


def test_format_spending_plan_renders_the_computed_numbers() -> None:
    text = format_spending_plan(make_spending_plan())

    assert text == (
        "Plano de gastos de setembro/2026\n"
        "Total: R$ 490,00 (7 lançamentos) | +53% vs período anterior "
        "(R$ 320,00)\n"
        "\n"
        "Top categorias:\n"
        "- Transporte: R$ 200,00 (41% do total, +100% vs período anterior)\n"
        "- Alimentação: R$ 150,00 (31% do total, +88% vs período anterior)\n"
        "- Lazer: R$ 50,00 (10% do total, 0% vs período anterior)\n"
        "\n"
        "Cortes sugeridos:\n"
        "- Transporte: R$ 24,50 de R$ 200,00\n"
        "- Alimentação: R$ 18,38 de R$ 150,00\n"
        "- Lazer: R$ 6,12 de R$ 50,00\n"
        "\n"
        "Meta de economia: R$ 49,00"
    )


def test_format_spending_plan_appends_the_narrative() -> None:
    text = format_spending_plan(
        make_spending_plan(narrative="Corte transporte e lazer.")
    )

    assert text.endswith(
        "Meta de economia: R$ 49,00\n\nCorte transporte e lazer."
    )


def test_format_spending_plan_for_an_empty_window() -> None:
    text = format_spending_plan(make_spending_plan(count=0))

    assert text == (
        "Plano de gastos de setembro/2026\n\n"
        "Nenhum gasto no período analisado."
    )
