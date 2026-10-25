"""Unit tests for pt-BR month-name period resolution."""

from __future__ import annotations

from datetime import date

import pytest

from myfinance.application.periods import resolve_period

TODAY = date(2026, 10, 22)


def test_current_month_name_is_capped_at_today() -> None:
    assert resolve_period("em outubro", today=TODAY) == (
        date(2026, 10, 1),
        date(2026, 10, 22),
    )


def test_month_name_with_explicit_year_is_a_full_month() -> None:
    assert resolve_period("outubro de 2025", today=TODAY) == (
        date(2025, 10, 1),
        date(2025, 10, 31),
    )


def test_month_name_with_slash_year_is_a_full_month() -> None:
    assert resolve_period("outubro/2025", today=TODAY) == (
        date(2025, 10, 1),
        date(2025, 10, 31),
    )


def test_abbreviated_month_with_slash_year_is_a_full_month() -> None:
    assert resolve_period("set/2026", today=TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )


def test_named_month_wins_over_the_generic_do_mes_marker() -> None:
    assert resolve_period(
        "lançamentos do mês de set/2026", today=TODAY
    ) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )


def test_future_month_name_uses_the_previous_year() -> None:
    assert resolve_period("em dezembro", today=TODAY) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )


def test_past_month_name_uses_the_current_year() -> None:
    assert resolve_period("em outubro", today=date(2027, 2, 10)) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )


def test_accented_month_name_is_recognised() -> None:
    assert resolve_period("em março", today=TODAY) == (
        date(2026, 3, 1),
        date(2026, 3, 31),
    )


def test_month_name_inside_a_question_is_recognised() -> None:
    assert resolve_period(
        "quanto gastei com uber em outubro de 2025?", today=TODAY
    ) == (
        date(2025, 10, 1),
        date(2025, 10, 31),
    )


@pytest.mark.parametrize(
    "reference",
    [
        None,
        "",
        "   ",
        "resumo",
        "gastei 45",
        "em banana",
        "quanto gastei com uber",
    ],
)
def test_references_without_a_month_return_none(
    reference: str | None,
) -> None:
    assert resolve_period(reference, today=TODAY) is None


def test_invalid_explicit_year_returns_none() -> None:
    assert resolve_period("outubro de 0000", today=TODAY) is None


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("esse mes", (date(2026, 10, 1), TODAY)),
        ("mes passado", (date(2026, 9, 1), date(2026, 9, 30))),
        ("mes que vem", (date(2026, 11, 1), date(2026, 11, 30))),
        ("essa semana", (date(2026, 10, 19), TODAY)),
        ("semana passada", (date(2026, 10, 12), date(2026, 10, 18))),
        ("ultimos 7 dias", (date(2026, 10, 16), TODAY)),
        ("ultimos 30 dias", (date(2026, 9, 23), TODAY)),
    ],
)
def test_existing_markers_keep_their_ranges(
    reference: str, expected: tuple[date, date]
) -> None:
    assert resolve_period(reference, today=TODAY) == expected


def test_existing_marker_takes_precedence_over_a_month_name() -> None:
    assert resolve_period(
        "gastos do mes passado, nao em outubro", today=TODAY
    ) == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
