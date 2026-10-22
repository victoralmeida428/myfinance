"""Unit tests for the grounded spending-plan use case."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import uuid4

from myfinance.application.dto import SpendingPlanMessage
from myfinance.application.errors import ProviderError
from myfinance.application.use_cases import GetSpendingPlanUseCase
from myfinance.domain.banking import BankExpense
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money

TODAY = date(2026, 10, 15)
CREATED_AT = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


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


class FakeNarrator:
    def __init__(self, narrative: str | None = "Corte transporte e lazer.") -> None:
        self._narrative = narrative
        self.plans: list[SpendingPlanMessage] = []

    async def narrate(self, plan: SpendingPlanMessage) -> str | None:
        self.plans.append(plan)
        return self._narrative


class FailingNarrator:
    async def narrate(self, plan: SpendingPlanMessage) -> str | None:
        raise ProviderError("narrator down")


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
) -> BankExpense:
    return BankExpense(
        id=uuid4(),
        day=day,
        description=description,
        amount_cents=cents,
        category=category,
        institution="Nubank",
    )


def september_entries() -> tuple[Entry, ...]:
    return (
        make_entry(
            date(2026, 9, 3), 10000, Category.ALIMENTACAO, "drogaria"
        ),
        make_entry(date(2026, 9, 9), 5000, Category.ALIMENTACAO, "mercado"),
        make_entry(
            date(2026, 9, 10),
            99999,
            Category.ALIMENTACAO,
            "previsão de mercado",
            kind=EntryKind.FORECAST,
        ),
        make_entry(date(2026, 8, 1), 70000, Category.OUTROS, "fora da janela"),
    )


def september_bank() -> tuple[BankExpense, ...]:
    return (
        make_bank_expense(
            date(2026, 9, 3),
            10000,
            Category.ALIMENTACAO,
            "compra no debito|drogaria nova valqueir",
        ),
        make_bank_expense(
            date(2026, 9, 4),
            20000,
            Category.TRANSPORTE,
            "dl*uberrides",
        ),
        make_bank_expense(
            date(2026, 9, 5), 5000, Category.LAZER, "pagamento|netflix"
        ),
        make_bank_expense(
            date(2026, 9, 6),
            3000,
            Category.OUTROS,
            "transferencia enviada|joao",
        ),
        make_bank_expense(
            date(2026, 9, 7),
            4000,
            Category.SERVICOS,
            "pagamento efetuado|energia",
        ),
        make_bank_expense(
            date(2026, 9, 8), 2000, Category.SAUDE, "compra|farmacia"
        ),
        make_bank_expense(
            date(2026, 8, 10),
            8000,
            Category.ALIMENTACAO,
            "compra no debito|mercado",
        ),
        make_bank_expense(
            date(2026, 8, 11),
            10000,
            Category.TRANSPORTE,
            "compra no debito|uber",
        ),
        make_bank_expense(
            date(2026, 8, 12),
            5000,
            Category.LAZER,
            "compra no debito|cinema",
        ),
        make_bank_expense(
            date(2026, 8, 13),
            3000,
            Category.OUTROS,
            "compra no debito|presente",
        ),
        make_bank_expense(
            date(2026, 8, 14),
            4000,
            Category.SERVICOS,
            "compra no debito|energia",
        ),
        make_bank_expense(
            date(2026, 8, 15),
            2000,
            Category.SAUDE,
            "compra no debito|farmacia",
        ),
    )


def build_use_case(
    *,
    entries: Sequence[Entry] = (),
    bank: Sequence[BankExpense] = (),
    narrator: FakeNarrator | FailingNarrator | None = None,
    today: date = TODAY,
) -> GetSpendingPlanUseCase:
    return GetSpendingPlanUseCase(
        InMemoryEntryRepository(entries),
        FakeBankExpenses(bank),
        FixedClock(today),
        narrator,
    )


async def test_default_period_is_the_previous_calendar_month() -> None:
    use_case = build_use_case(entries=september_entries(), bank=september_bank())

    plan = await use_case.execute("onde posso cortar gastos?")

    assert plan.start == date(2026, 9, 1)
    assert plan.end == date(2026, 9, 30)
    assert plan.total_cents == 49000
    assert plan.count == 7
    assert plan.previous_total_cents == 32000


async def test_categories_carry_share_and_delta_versus_the_previous_window() -> None:
    use_case = build_use_case(entries=september_entries(), bank=september_bank())

    plan = await use_case.execute("como economizar mais?")

    assert [
        (
            category.category,
            category.total_cents,
            category.share_percent,
            category.previous_cents,
            category.delta_percent,
        )
        for category in plan.categories
    ] == [
        (Category.TRANSPORTE, 20000, 41, 10000, 100),
        (Category.ALIMENTACAO, 15000, 31, 8000, 88),
        (Category.LAZER, 5000, 10, 5000, 0),
        (Category.SERVICOS, 4000, 8, 4000, 0),
        (Category.OUTROS, 3000, 6, 3000, 0),
        (Category.SAUDE, 2000, 4, 2000, 0),
    ]


async def test_top_merchants_clean_bank_prefixes_and_group_duplicates() -> None:
    entries = (
        make_entry(
            date(2026, 9, 2), 10000, Category.ALIMENTACAO, "compra antiga"
        ),
    )
    bank = (
        make_bank_expense(
            date(2026, 9, 3),
            10000,
            Category.ALIMENTACAO,
            "compra no debito|drogaria nova valqueir",
        ),
        make_bank_expense(
            date(2026, 9, 4),
            5000,
            Category.ALIMENTACAO,
            "compra no débito|DROGARIA NOVA VALQUEIR",
        ),
        make_bank_expense(
            date(2026, 9, 5),
            3000,
            Category.OUTROS,
            "transferencia enviada pelo pix|Maria Silva",
        ),
        make_bank_expense(
            date(2026, 9, 6), 2000, Category.LAZER, "pagamento|Netflix"
        ),
    )
    use_case = build_use_case(entries=entries, bank=bank)

    plan = await use_case.execute("faça um plano de gastos")

    assert plan.merchants[0].name == "drogaria nova valqueir"
    assert plan.merchants[0].total_cents == 15000
    assert plan.merchants[0].count == 2
    assert plan.merchants[1].name == "compra antiga"
    assert plan.merchants[2].name == "maria silva"
    assert plan.merchants[3].name == "netflix"
    assert all(
        merchant.name == merchant.name.lower() for merchant in plan.merchants
    )


async def test_target_is_ten_percent_of_the_total() -> None:
    use_case = build_use_case(entries=september_entries(), bank=september_bank())

    plan = await use_case.execute()

    assert plan.target_cents == 4900


async def test_cuts_are_proportional_and_sum_to_the_target() -> None:
    use_case = build_use_case(entries=september_entries(), bank=september_bank())

    plan = await use_case.execute()

    assert [cut.label for cut in plan.cuts] == [
        "Transporte",
        "Alimentação",
        "Lazer",
    ]
    assert [cut.cut_cents for cut in plan.cuts] == [2450, 1838, 612]
    assert sum(cut.cut_cents for cut in plan.cuts) == plan.target_cents


async def test_services_and_health_are_never_cut() -> None:
    use_case = build_use_case(
        bank=(
            make_bank_expense(
                date(2026, 9, 3),
                10000,
                Category.SERVICOS,
                "pagamento|energia",
            ),
            make_bank_expense(
                date(2026, 9, 4), 5000, Category.SAUDE, "compra|farmacia"
            ),
        )
    )

    plan = await use_case.execute()

    assert plan.total_cents == 15000
    assert plan.cuts == ()


async def test_manual_entry_matching_a_bank_expense_is_counted_once() -> None:
    entries = (
        make_entry(
            date(2026, 9, 3), 10000, Category.ALIMENTACAO, "drogaria"
        ),
        make_entry(date(2026, 9, 3), 2000, Category.ALIMENTACAO, "padaria"),
    )
    bank = (
        make_bank_expense(
            date(2026, 9, 3),
            10000,
            Category.ALIMENTACAO,
            "compra no debito|drogaria",
        ),
    )
    use_case = build_use_case(entries=entries, bank=bank)

    plan = await use_case.execute()

    assert plan.total_cents == 12000
    assert plan.count == 2


async def test_forecast_entries_never_count() -> None:
    use_case = build_use_case(
        entries=(
            make_entry(
                date(2026, 9, 10),
                99999,
                Category.ALIMENTACAO,
                "previsão",
                kind=EntryKind.FORECAST,
            ),
        )
    )

    plan = await use_case.execute()

    assert plan.total_cents == 0
    assert plan.count == 0


async def test_no_data_returns_an_empty_plan_for_the_previous_month() -> None:
    use_case = build_use_case()

    plan = await use_case.execute("onde posso cortar gastos?")

    assert plan.start == date(2026, 9, 1)
    assert plan.end == date(2026, 9, 30)
    assert plan.total_cents == 0
    assert plan.count == 0
    assert plan.previous_total_cents == 0
    assert plan.categories == ()
    assert plan.merchants == ()
    assert plan.target_cents == 0
    assert plan.cuts == ()
    assert plan.narrative is None


async def test_text_period_uses_a_thirty_day_window() -> None:
    entries = (
        make_entry(date(2026, 8, 16), 9000, Category.OUTROS, "fora anterior"),
        make_entry(date(2026, 8, 17), 7000, Category.OUTROS, "anterior"),
        make_entry(date(2026, 9, 15), 1000, Category.OUTROS, "fora atual"),
        make_entry(date(2026, 9, 16), 2000, Category.OUTROS, "atual"),
        make_entry(date(2026, 10, 15), 3000, Category.OUTROS, "hoje"),
        make_entry(date(2026, 10, 16), 4000, Category.OUTROS, "futuro"),
    )
    use_case = build_use_case(entries=entries)

    plan = await use_case.execute("últimos 30 dias")

    assert plan.start == date(2026, 9, 16)
    assert plan.end == date(2026, 10, 15)
    assert plan.total_cents == 5000
    assert plan.count == 2
    assert plan.previous_total_cents == 8000


async def test_narrative_is_attached_without_changing_the_numbers() -> None:
    narrator = FakeNarrator("Corte transporte e lazer para economizar.")
    use_case = build_use_case(
        entries=september_entries(),
        bank=september_bank(),
        narrator=narrator,
    )

    plan = await use_case.execute()

    assert plan.narrative == "Corte transporte e lazer para economizar."
    assert plan.total_cents == 49000
    assert plan.target_cents == 4900
    assert narrator.plans[0].narrative is None


async def test_narrator_failure_falls_back_to_no_narrative() -> None:
    use_case = build_use_case(
        entries=september_entries(),
        bank=september_bank(),
        narrator=FailingNarrator(),
    )

    plan = await use_case.execute()

    assert plan.narrative is None
    assert plan.total_cents == 49000
