"""Unit tests for the shared manual/bank expense reconciliation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category, coerce_category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.expenses import manual_expenses_not_in_bank
from myfinance.domain.money import Money

TODAY = date(2026, 10, 20)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def make_entry(
    day: date,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
    amount_cents: int = 4500,
    description: str = "almoço",
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(amount_cents),
        description=description,
        category=Category.ALIMENTACAO,
        created_at=CREATED_AT,
    )


def make_bank_expense(
    day: date,
    *,
    amount_cents: int = 4500,
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        amount_cents=amount_cents,
        category=Category.ALIMENTACAO,
        description="almoço",
        institution=None,
    )


def test_coerce_category_accepts_enums_and_valid_strings() -> None:
    assert coerce_category(Category.SAUDE) is Category.SAUDE
    assert coerce_category("saude") is Category.SAUDE


def test_coerce_category_falls_back_to_outros() -> None:
    assert coerce_category(None) is Category.OUTROS
    assert coerce_category("unknown") is Category.OUTROS
    assert coerce_category(42) is Category.OUTROS


def test_forecasts_are_excluded() -> None:
    entry = make_entry(TODAY, kind=EntryKind.FORECAST)

    assert manual_expenses_not_in_bank((entry,), ()) == ()


def test_manual_duplicate_of_a_bank_expense_is_excluded() -> None:
    entry = make_entry(TODAY)
    bank = make_bank_expense(TODAY)

    assert manual_expenses_not_in_bank((entry,), (bank,)) == ()


def test_same_amount_on_a_different_day_is_kept() -> None:
    entry = make_entry(date(2026, 10, 19))
    bank = make_bank_expense(TODAY)

    assert manual_expenses_not_in_bank((entry,), (bank,)) == (entry,)


def test_bank_expense_without_a_manual_pair_is_unaffected() -> None:
    bank = make_bank_expense(TODAY)

    assert manual_expenses_not_in_bank((), (bank,)) == ()


def test_manual_order_is_preserved() -> None:
    first = make_entry(TODAY, description="primeiro")
    second = make_entry(TODAY, amount_cents=3000, description="segundo")

    result = manual_expenses_not_in_bank((first, second), ())

    assert result == (first, second)
