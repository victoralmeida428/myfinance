"""Unit tests for pt-BR year period resolution."""

from __future__ import annotations

from datetime import date

import pytest

from myfinance.application.periods import resolve_period

TODAY = date(2026, 10, 22)


@pytest.mark.parametrize(
    "reference",
    ["esse ano", "este ano", "nesse ano", "neste ano", "ano atual"],
)
def test_current_year_markers_start_on_january_first_and_cap_at_today(
    reference: str,
) -> None:
    assert resolve_period(reference, today=TODAY) == (
        date(2026, 1, 1),
        TODAY,
    )


@pytest.mark.parametrize("reference", ["resumo do ano", "resumo no ano"])
def test_current_year_phrases_start_on_january_first_and_cap_at_today(
    reference: str,
) -> None:
    assert resolve_period(reference, today=TODAY) == (
        date(2026, 1, 1),
        TODAY,
    )


def test_current_week_phrase_resolves_to_monday_through_today() -> None:
    assert resolve_period("resumo da semana", today=TODAY) == (
        date(2026, 10, 19),
        TODAY,
    )


def test_last_week_phrase_wins_over_current_week_marker() -> None:
    assert resolve_period("resumo da semana passada", today=TODAY) == (
        date(2026, 10, 12),
        date(2026, 10, 18),
    )


def test_last_year_phrase_wins_over_current_year_marker() -> None:
    assert resolve_period("resumo do ano passado", today=TODAY) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


@pytest.mark.parametrize("reference", ["ano passado", "ultimo ano"])
def test_last_year_markers_resolve_to_the_full_previous_year(
    reference: str,
) -> None:
    assert resolve_period(reference, today=TODAY) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


@pytest.mark.parametrize("reference", ["ano que vem", "proximo ano"])
def test_next_year_markers_resolve_to_the_full_next_year(
    reference: str,
) -> None:
    assert resolve_period(reference, today=TODAY) == (
        date(2027, 1, 1),
        date(2027, 12, 31),
    )


@pytest.mark.parametrize("reference", ["em 2025", "2025"])
def test_explicit_past_year_resolves_to_the_full_year(reference: str) -> None:
    assert resolve_period(reference, today=TODAY) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


def test_explicit_current_year_caps_at_today() -> None:
    assert resolve_period("em 2026", today=TODAY) == (
        date(2026, 1, 1),
        TODAY,
    )


def test_explicit_future_year_resolves_to_the_full_year() -> None:
    assert resolve_period("em 2027", today=TODAY) == (
        date(2027, 1, 1),
        date(2027, 12, 31),
    )


def test_month_with_explicit_year_still_resolves_to_that_month() -> None:
    assert resolve_period("outubro de 2025", today=TODAY) == (
        date(2025, 10, 1),
        date(2025, 10, 31),
    )


def test_year_marker_inside_a_question_is_recognised() -> None:
    assert resolve_period(
        "quanto gastei de gasolina esse ano?", today=TODAY
    ) == (
        date(2026, 1, 1),
        TODAY,
    )


@pytest.mark.parametrize(
    "reference",
    ["12/10/2025", "2025-10-12", "em 1899", "em 2100"],
)
def test_years_embedded_in_dates_or_out_of_range_are_ignored(
    reference: str,
) -> None:
    assert resolve_period(reference, today=TODAY) is None
