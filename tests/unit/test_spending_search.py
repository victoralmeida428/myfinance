"""Unit tests for free-form spending questions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from myfinance.application.dto import SpendingAnswerMessage, SpendingQuery
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import SearchSpendingUseCase
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money

TODAY = date(2026, 10, 20)
NOVEMBER = date(2026, 11, 15)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today

    def now(self) -> datetime:
        return CREATED_AT


class InMemoryEntryRepository:
    def __init__(self, entries: Sequence[Entry] = ()) -> None:
        self.entries: list[Entry] = list(entries)
        self.calls: list[tuple[date, date]] = []

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        self.calls.append((start, end))
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class FakeBankExpenses:
    def __init__(self, expenses: Sequence[BankExpense] = ()) -> None:
        self._expenses = tuple(expenses)
        self.calls: list[tuple[date, date]] = []

    async def expenses(
        self, start: date, end: date
    ) -> tuple[BankExpense, ...]:
        self.calls.append((start, end))
        return tuple(
            expense
            for expense in self._expenses
            if start <= expense.day <= end
        )


class RaisingBankExpenses:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    async def expenses(self, start: date, end: date) -> Sequence[BankExpense]:
        self.calls.append((start, end))
        raise ProviderError("o banco não respondeu")


class FakeSpendingParser:
    def __init__(self, query: SpendingQuery | None) -> None:
        self._query = query
        self.calls: list[tuple[str, date]] = []

    async def parse(self, text: str, *, today: date) -> SpendingQuery | None:
        self.calls.append((text, today))
        return self._query


class FakeReferences:
    def __init__(self, reference: str | None = None) -> None:
        self._reference = reference
        self.calls: list[str] = []

    def extract(self, text: str) -> str | None:
        self.calls.append(text)
        return self._reference


class FakeDates:
    def __init__(self, day: date | None = None) -> None:
        self._day = day
        self.calls: list[tuple[str | None, date]] = []

    def resolve(self, reference: str | None, *, today: date) -> date | None:
        self.calls.append((reference, today))
        return self._day


def make_entry(
    day: date,
    cents: int,
    category: Category,
    description: str,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(cents),
        description=description,
        category=category,
        created_at=CREATED_AT,
    )


def make_bank_expense(
    day: date,
    cents: int,
    category: Category,
    description: str,
    *,
    raw_category: str | None = None,
    description_raw: str | None = None,
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description=description,
        amount_cents=cents,
        category=category,
        institution="Nubank",
        raw_category=raw_category,
        description_raw=description_raw,
    )


def build_use_case(
    parser: FakeSpendingParser,
    entries: Sequence[Entry] = (),
    bank: FakeBankExpenses | RaisingBankExpenses | None = None,
    today: date = TODAY,
) -> SearchSpendingUseCase:
    return SearchSpendingUseCase(
        InMemoryEntryRepository(entries),
        bank,
        FixedClock(today),
        FakeReferences(),
        FakeDates(),
        parser,
    )


async def test_category_match_sums_only_that_category() -> None:
    bank = FakeBankExpenses(
        (
            make_bank_expense(
                date(2026, 10, 8), 3000, Category.ALIMENTACAO, "restaurante"
            ),
            make_bank_expense(
                date(2026, 10, 9), 7000, Category.TRANSPORTE, "combustível"
            ),
        )
    )
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", Category.ALIMENTACAO, ())
        ),
        (
            make_entry(date(2026, 10, 5), 4500, Category.ALIMENTACAO, "almoço"),
            make_entry(date(2026, 10, 6), 2000, Category.TRANSPORTE, "ônibus"),
            make_entry(date(2026, 10, 7), 1500, Category.ALIMENTACAO, "padaria"),
        ),
        bank,
    )

    answer = await use_case.execute("quanto gastei com alimentos em outubro?")

    assert answer is not None
    assert answer.start == date(2026, 10, 1)
    assert answer.end == TODAY
    assert answer.label == "Alimentação"
    assert answer.total_cents == 9000
    assert answer.count == 3
    assert answer.category is Category.ALIMENTACAO


async def test_keyword_match_ignores_category() -> None:
    use_case = build_use_case(
        FakeSpendingParser(SpendingQuery("outubro", None, ("uber",))),
        (
            make_entry(
                date(2026, 10, 5), 2500, Category.TRANSPORTE, "Uber Centro"
            ),
            make_entry(
                date(2026, 10, 6), 1800, Category.TRANSPORTE, "Uber para casa"
            ),
            make_entry(date(2026, 10, 7), 500, Category.TRANSPORTE, "Ônibus"),
            make_entry(date(2026, 10, 8), 4000, Category.ALIMENTACAO, "almoço"),
        ),
        FakeBankExpenses(
            (
                make_bank_expense(
                    date(2026, 10, 9), 2200, Category.TRANSPORTE, "UBER *TRIP"
                ),
                make_bank_expense(
                    date(2026, 10, 10), 900, Category.TRANSPORTE, "99 POP"
                ),
            )
        ),
    )

    answer = await use_case.execute("quanto gastei de uber em outubro?")

    assert answer is not None
    assert answer.total_cents == 6500
    assert answer.count == 3
    assert answer.label == "uber"
    assert answer.category is None


async def test_posto_de_gasolina_matches_raw_category_and_descriptions() -> None:
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", None, ("posto", "gasolina"))
        ),
        (
            make_entry(
                date(2026, 10, 3), 12000, Category.TRANSPORTE, "Abasteci no posto"
            ),
            make_entry(date(2026, 10, 4), 5000, Category.TRANSPORTE, "Uber"),
        ),
        FakeBankExpenses(
            (
                make_bank_expense(
                    date(2026, 10, 5),
                    15000,
                    Category.TRANSPORTE,
                    "Compra no débito",
                    raw_category="Gas Stations",
                    description_raw="POSTO IPIRANGA",
                ),
                make_bank_expense(
                    date(2026, 10, 6),
                    8000,
                    Category.TRANSPORTE,
                    "Mercado",
                    raw_category="Groceries",
                    description_raw="MERCADO",
                ),
            )
        ),
    )

    answer = await use_case.execute("quanto gastei no posto de gasolina?")

    assert answer is not None
    assert answer.total_cents == 27000
    assert answer.count == 2


async def test_raw_category_participates_in_the_haystack() -> None:
    use_case = build_use_case(
        FakeSpendingParser(SpendingQuery("outubro", None, ("gas",))),
        (),
        FakeBankExpenses(
            (
                make_bank_expense(
                    date(2026, 10, 5),
                    1000,
                    Category.TRANSPORTE,
                    "compra",
                    raw_category="Gas Stations",
                    description_raw="loja",
                ),
            )
        ),
    )

    answer = await use_case.execute("quanto gastei de gas?")

    assert answer is not None
    assert answer.total_cents == 1000
    assert answer.count == 1


async def test_manual_expense_matching_bank_expense_counts_once() -> None:
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", Category.ALIMENTACAO, ())
        ),
        (
            make_entry(
                date(2026, 10, 10), 4500, Category.ALIMENTACAO, "almoço"
            ),
        ),
        FakeBankExpenses(
            (
                make_bank_expense(
                    date(2026, 10, 10), 4500, Category.ALIMENTACAO, "restaurante"
                ),
                make_bank_expense(
                    date(2026, 10, 11), 2000, Category.ALIMENTACAO, "padaria"
                ),
            )
        ),
    )

    answer = await use_case.execute("quanto gastei com alimentos?")

    assert answer is not None
    assert answer.total_cents == 6500
    assert answer.count == 2


async def test_forecast_entries_never_count() -> None:
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", Category.ALIMENTACAO, ())
        ),
        (
            make_entry(
                date(2026, 10, 10),
                9999,
                Category.ALIMENTACAO,
                "previsão de almoço",
                kind=EntryKind.FORECAST,
            ),
            make_entry(date(2026, 10, 11), 1000, Category.ALIMENTACAO, "padaria"),
        ),
    )

    answer = await use_case.execute("quanto gastei com alimentos?")

    assert answer is not None
    assert answer.total_cents == 1000
    assert answer.count == 1


async def test_zero_matches_answers_with_the_category_label() -> None:
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", Category.TRANSPORTE, ())
        ),
        (
            make_entry(date(2026, 10, 5), 4500, Category.ALIMENTACAO, "almoço"),
        ),
    )

    answer = await use_case.execute("quanto gastei de transporte?")

    assert answer is not None
    assert answer.total_cents == 0
    assert answer.count == 0
    assert answer.label == "Transporte"


async def test_zero_matches_answers_with_the_joined_keywords() -> None:
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", None, ("cinema", "teatro"))
        )
    )

    answer = await use_case.execute("quanto gastei com cinema e teatro?")

    assert answer is not None
    assert answer.total_cents == 0
    assert answer.count == 0
    assert answer.label == "cinema, teatro"


async def test_defaults_to_current_month_without_period_or_date() -> None:
    repository = InMemoryEntryRepository(
        (
            make_entry(date(2026, 9, 30), 1000, Category.ALIMENTACAO, "mercado"),
            make_entry(date(2026, 10, 1), 2000, Category.ALIMENTACAO, "mercado"),
            make_entry(date(2026, 10, 20), 3000, Category.ALIMENTACAO, "mercado"),
            make_entry(date(2026, 10, 21), 4000, Category.ALIMENTACAO, "mercado"),
        )
    )
    references = FakeReferences()
    dates = FakeDates()
    use_case = SearchSpendingUseCase(
        repository,
        None,
        FixedClock(TODAY),
        references,
        dates,
        FakeSpendingParser(SpendingQuery(None, Category.ALIMENTACAO, ())),
    )

    answer = await use_case.execute("quanto gastei com alimentos?")

    assert answer is not None
    assert answer.start == date(2026, 10, 1)
    assert answer.end == TODAY
    assert answer.total_cents == 5000
    assert answer.count == 2
    assert references.calls == ["quanto gastei com alimentos?"]
    assert dates.calls == []


async def test_single_day_reference_falls_back_to_that_day() -> None:
    repository = InMemoryEntryRepository(
        (
            make_entry(date(2026, 10, 18), 1000, Category.ALIMENTACAO, "mercado"),
            make_entry(date(2026, 10, 19), 2000, Category.ALIMENTACAO, "mercado"),
            make_entry(date(2026, 10, 20), 4000, Category.ALIMENTACAO, "mercado"),
        )
    )
    references = FakeReferences("ontem")
    dates = FakeDates(date(2026, 10, 19))
    use_case = SearchSpendingUseCase(
        repository,
        None,
        FixedClock(TODAY),
        references,
        dates,
        FakeSpendingParser(SpendingQuery(None, Category.ALIMENTACAO, ())),
    )

    answer = await use_case.execute("quanto gastei ontem com alimentos?")

    assert answer is not None
    assert answer.start == date(2026, 10, 19)
    assert answer.end == date(2026, 10, 19)
    assert answer.total_cents == 2000
    assert answer.count == 1
    assert references.calls == ["quanto gastei ontem com alimentos?"]
    assert dates.calls == [("ontem", TODAY)]


async def test_explicit_month_name_uses_the_whole_october_range() -> None:
    use_case = build_use_case(
        FakeSpendingParser(SpendingQuery("outubro", Category.LAZER, ())),
        (
            make_entry(date(2026, 10, 1), 1000, Category.LAZER, "cinema"),
            make_entry(date(2026, 10, 31), 2000, Category.LAZER, "teatro"),
            make_entry(date(2026, 11, 1), 3000, Category.LAZER, "show"),
        ),
        today=NOVEMBER,
    )

    answer = await use_case.execute("quanto gastei de lazer em outubro?")

    assert answer is not None
    assert answer.start == date(2026, 10, 1)
    assert answer.end == date(2026, 10, 31)
    assert answer.total_cents == 3000
    assert answer.count == 2


async def test_parser_returning_none_yields_no_answer() -> None:
    use_case = build_use_case(FakeSpendingParser(None))

    answer = await use_case.execute("qualquer coisa")

    assert answer is None


async def test_bank_provider_error_propagates() -> None:
    bank = RaisingBankExpenses()
    use_case = build_use_case(
        FakeSpendingParser(
            SpendingQuery("outubro", Category.ALIMENTACAO, ())
        ),
        bank=bank,
    )

    with pytest.raises(ProviderError, match="o banco não respondeu"):
        await use_case.execute("quanto gastei com alimentos?")

    assert bank.calls == [(date(2026, 10, 1), TODAY)]


async def test_answer_message_carries_the_query_fields() -> None:
    query = SpendingQuery("outubro", None, ("uber",))
    use_case = build_use_case(
        FakeSpendingParser(query),
        (make_entry(date(2026, 10, 5), 2500, Category.TRANSPORTE, "Uber"),),
    )

    answer = await use_case.execute("quanto gastei de uber?")

    assert isinstance(answer, SpendingAnswerMessage)
    assert answer.keywords == ("uber",)
    assert answer.category is None
