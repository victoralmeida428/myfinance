"""Unit tests for the "which month did I spend the most?" insight."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.application.dto import MonthlyExpense, TopMonthMessage
from myfinance.application.use_cases import (
    GetTopSpendingMonthUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
)
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.presentation.telegram.formatting import format_top_month

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def today(self) -> date:
        return self._now.date()

    def now(self) -> datetime:
        return self._now


class InMemoryEntryRepository:
    def __init__(self, entries: list[Entry] | None = None) -> None:
        self.entries: list[Entry] = list(entries or [])

    async def add(self, entry: Entry) -> None:
        self.entries.append(entry)

    async def list_by_day(self, day: date) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.day == day)

    async def list_between(self, start: date, end: date) -> tuple[Entry, ...]:
        return tuple(
            entry for entry in self.entries if start <= entry.day <= end
        )


class FakeBankExpenses:
    def __init__(self, expenses: tuple[BankExpense, ...] = ()) -> None:
        self._expenses = expenses
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


class FakeSummaryGate:
    def __init__(self, decision: bool) -> None:
        self._decision = decision

    async def should_summarize(self, text: str) -> bool:
        return self._decision


class ExplodingSummary:
    """A summary stand-in that fails if the top-month branch is bypassed."""

    async def execute(self, reference: str | None = None) -> object:
        raise AssertionError("the summary path must not be used")


def make_entry(
    day: date,
    cents: int,
    category: Category,
    *,
    kind: EntryKind = EntryKind.EXPENSE,
) -> Entry:
    return Entry(
        id=uuid4(),
        kind=kind,
        day=day,
        amount=Money(cents),
        description="lançamento",
        category=category,
        created_at=CREATED_AT,
    )


def make_bank_expense(
    day: date,
    cents: int,
    category: Category,
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description="compra no débito",
        amount_cents=cents,
        category=category,
        institution="Nubank",
    )


def _repository() -> InMemoryEntryRepository:
    return InMemoryEntryRepository(
        [
            make_entry(date(2026, 9, 10), 50000, Category.LAZER),
            make_entry(date(2026, 10, 5), 30000, Category.SERVICOS),
            make_entry(
                date(2026, 10, 6),
                99999,
                Category.OUTROS,
                kind=EntryKind.FORECAST,
            ),
        ]
    )


def _bank_expenses() -> FakeBankExpenses:
    return FakeBankExpenses(
        (
            make_bank_expense(date(2026, 9, 10), 100000, Category.TRANSPORTE),
            make_bank_expense(date(2026, 8, 12), 200000, Category.ALIMENTACAO),
            make_bank_expense(date(2026, 10, 5), 30000, Category.SERVICOS),
        )
    )


async def _build_message() -> TopMonthMessage:
    use_case = GetTopSpendingMonthUseCase(
        _repository(), _bank_expenses(), FixedClock(NOW)
    )
    return await use_case.execute()


async def test_ranks_the_last_months_by_realized_spending() -> None:
    message = await _build_message()

    assert message.window_start == date(2025, 11, 1)
    assert message.window_end == TODAY
    assert message.ranking == (
        MonthlyExpense(year=2026, month=8, expense_cents=200000),
        MonthlyExpense(year=2026, month=9, expense_cents=150000),
        MonthlyExpense(year=2026, month=10, expense_cents=30000),
    )


async def test_forecasts_are_ignored_and_matching_manual_expenses_deduped() -> None:
    message = await _build_message()

    october = message.ranking[2]
    assert october.month == 10
    assert october.expense_cents == 30000


async def test_winner_balances_come_from_the_winner_month() -> None:
    message = await _build_message()

    assert len(message.winner_balances) == 1
    balance = message.winner_balances[0]
    assert balance.category is Category.ALIMENTACAO
    assert balance.expense_cents == 200000
    assert balance.manual_expense_cents == 0
    assert balance.bank_expense_cents == 200000


async def test_bank_window_covers_the_last_twelve_months() -> None:
    bank = _bank_expenses()
    use_case = GetTopSpendingMonthUseCase(
        _repository(), bank, FixedClock(NOW)
    )

    await use_case.execute()

    assert bank.calls == [(date(2025, 11, 1), TODAY)]


async def test_handle_message_routes_the_top_month_question() -> None:
    clock = FixedClock(NOW)
    repository = _repository()
    exploding = ExplodingSummary()
    use_case = HandleMessageUseCase(
        DeterministicMessageParser(PortugueseDateResolver()),
        RegisterEntryUseCase(repository, clock),
        clock,
        exploding,  # type: ignore[arg-type]
        PortugueseDateReferenceExtractor(),
        exploding,  # type: ignore[arg-type]
        FakeSummaryGate(True),
        GetTopSpendingMonthUseCase(repository, _bank_expenses(), clock),
    )

    result = await use_case.execute("Qual foi o mês que eu mais gastei?")

    assert isinstance(result, TopMonthMessage)
    assert result.ranking[0] == MonthlyExpense(
        year=2026, month=8, expense_cents=200000
    )


async def test_format_top_month_shows_the_winner_ranking_and_categories() -> None:
    text = format_top_month(await _build_message())

    assert "agosto/2026" in text
    assert "R$ 2.000,00" in text
    assert "Top 3:" in text
    assert "Categorias em agosto/2026:" in text
    assert "- Alimentação: R$ 2.000,00" in text
    assert "Nenhum gasto encontrado" not in text


async def test_empty_data_reports_no_spending() -> None:
    use_case = GetTopSpendingMonthUseCase(
        InMemoryEntryRepository(), FakeBankExpenses(), FixedClock(NOW)
    )

    message = await use_case.execute()

    assert message.ranking == ()
    assert message.winner_balances == ()
    assert "Nenhum gasto encontrado" in format_top_month(message)
