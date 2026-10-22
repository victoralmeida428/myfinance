"""Unit tests for the Pluggy bank-expense adapter (no network, no database)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from myfinance.domain.banking import (
    BankAccount,
    BankTransaction,
    PluggyItem,
)
from myfinance.domain.categories import Category
from myfinance.infrastructure.pluggy_bank_expenses import (
    PluggyBankExpenseProvider,
)

TODAY = date(2026, 10, 20)


class FakeItemRepository:
    """In-memory stand-in for the Pluggy item repository."""

    def __init__(self, items: Sequence[PluggyItem]) -> None:
        self._items = tuple(items)

    async def list_active(self) -> Sequence[PluggyItem]:
        return self._items


class FakeBankingProvider:
    """Returns pre-built accounts and transactions keyed by their ids."""

    def __init__(
        self,
        accounts: dict[UUID, Sequence[BankAccount]],
        transactions: dict[UUID, Sequence[BankTransaction]],
    ) -> None:
        self._accounts = accounts
        self._transactions = transactions
        self.transaction_calls: list[UUID] = []

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]:
        return self._accounts.get(item_id, ())

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]:
        self.transaction_calls.append(account_id)
        return self._transactions.get(account_id, ())


class FakeClassifier:
    """Records descriptions and returns a fixed category."""

    def __init__(self, category: Category | None) -> None:
        self._category = category
        self.calls: list[str] = []

    async def classify(self, text: str) -> Category | None:
        self.calls.append(text)
        return self._category


def make_item(name: str) -> PluggyItem:
    return PluggyItem(
        id=uuid4(),
        status="updated",
        error=None,
        updated_at=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        connector_name=name,
    )


def make_account(
    item: PluggyItem, account_type: str, name: str = "Conta"
) -> BankAccount:
    return BankAccount(
        id=uuid4(),
        item_id=item.id,
        type=account_type,
        name=name,
        balance_cents=0,
        currency="BRL",
    )


def make_transaction(
    account: BankAccount,
    *,
    description: str,
    amount_cents: int,
    category: str | None,
    direction: str,
    description_raw: str | None = None,
) -> BankTransaction:
    return BankTransaction(
        id=uuid4(),
        account_id=account.id,
        item_id=account.item_id,
        day=TODAY,
        description=description,
        amount_cents=amount_cents,
        currency="BRL",
        category=category,
        direction=direction,
        description_raw=description_raw,
    )


def build_provider(
    *,
    items: Sequence[PluggyItem],
    banking: FakeBankingProvider,
    classifier: FakeClassifier | None = None,
) -> PluggyBankExpenseProvider:
    return PluggyBankExpenseProvider(
        banking, FakeItemRepository(items), classifier or FakeClassifier(None)
    )


async def test_only_debits_with_non_bookkeeping_categories_become_expenses() -> None:
    bank_item = make_item("Nubank")
    card_item = make_item("Nubank Cartão")
    bank_account = make_account(bank_item, "BANK")
    card_account = make_account(card_item, "CREDIT", "Cartão")

    debit = make_transaction(
        bank_account,
        description="Compra no débito|SUPERMERCADO",
        amount_cents=-4550,
        category="Groceries",
        direction="DEBIT",
    )
    inflow = make_transaction(
        bank_account,
        description="Transferência Recebida",
        amount_cents=1000,
        category="Transfers",
        direction="CREDIT",
    )
    card_debit = make_transaction(
        card_account,
        description="Ebn *Tiktok Shop",
        amount_cents=11798,
        category="Clothing",
        direction="DEBIT",
    )
    card_payment = make_transaction(
        card_account,
        description="Pagamento recebido",
        amount_cents=-171594,
        category="Credit card payment",
        direction="CREDIT",
    )

    banking = FakeBankingProvider(
        {
            bank_item.id: (bank_account,),
            card_item.id: (card_account,),
        },
        {
            bank_account.id: (debit, inflow),
            card_account.id: (card_debit, card_payment),
        },
    )
    provider = build_provider(
        items=(bank_item, card_item), banking=banking
    )

    expenses = await provider.expenses(TODAY, TODAY)

    assert {expense.id for expense in expenses} == {debit.id, card_debit.id}
    by_id = {expense.id: expense for expense in expenses}

    groceries = by_id[debit.id]
    assert groceries.amount_cents == 4550
    assert groceries.category is Category.ALIMENTACAO
    assert groceries.institution == "Nubank"
    assert groceries.day == TODAY

    shopping = by_id[card_debit.id]
    assert shopping.amount_cents == 11798
    assert shopping.category is Category.OUTROS
    assert shopping.institution == "Nubank Cartão"

    assert all(expense.amount_cents > 0 for expense in expenses)
    assert banking.transaction_calls == [bank_account.id, card_account.id]


async def test_bookkeeping_categories_are_excluded_even_on_debits() -> None:
    item = make_item("Nubank")
    account = make_account(item, "BANK")
    excluded = [
        make_transaction(
            account,
            description=description,
            amount_cents=-1000,
            category=category,
            direction="DEBIT",
        )
        for description, category in (
            ("Pagamento de fatura", "Credit card payment"),
            ("Transferência enviada", "Transfers"),
            ("Transferência entre contas", "Same person transfer"),
            ("Aplicação", "Investments"),
        )
    ]
    banking = FakeBankingProvider(
        {item.id: (account,)}, {account.id: tuple(excluded)}
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_unmapped_category_falls_back_to_the_classifier() -> None:
    item = make_item("Nubank")
    account = make_account(item, "BANK")
    transaction = make_transaction(
        account,
        description="PIX MERCADO",
        amount_cents=-2500,
        category="Uncategorized",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        {item.id: (account,)}, {account.id: (transaction,)}
    )
    classifier = FakeClassifier(Category.SAUDE)
    provider = build_provider(
        items=(item,), banking=banking, classifier=classifier
    )

    expenses = await provider.expenses(TODAY, TODAY)

    assert classifier.calls == ["PIX MERCADO"]
    assert expenses[0].category is Category.SAUDE


async def test_classifier_abstention_falls_back_to_outros() -> None:
    item = make_item("Nubank")
    account = make_account(item, "BANK")
    transaction = make_transaction(
        account,
        description="LANÇAMENTO DESCONHECIDO",
        amount_cents=-900,
        category=None,
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        {item.id: (account,)}, {account.id: (transaction,)}
    )
    classifier = FakeClassifier(None)
    provider = build_provider(
        items=(item,), banking=banking, classifier=classifier
    )

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses[0].category is Category.OUTROS


async def test_no_active_items_returns_no_expenses() -> None:
    banking = FakeBankingProvider({}, {})
    provider = build_provider(items=(), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_raw_category_and_description_survive_mapping() -> None:
    item = make_item("Nubank")
    account = make_account(item, "BANK")
    transaction = make_transaction(
        account,
        description="POSTO IPIRANGA",
        amount_cents=-15000,
        category="Gas Stations",
        direction="DEBIT",
        description_raw="POSTO IPIRANGA",
    )
    banking = FakeBankingProvider(
        {item.id: (account,)}, {account.id: (transaction,)}
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    expense = expenses[0]
    assert expense.category is Category.TRANSPORTE
    assert expense.raw_category == "Gas Stations"
    assert expense.description_raw == "POSTO IPIRANGA"


async def test_missing_raw_category_and_description_yield_none() -> None:
    item = make_item("Nubank")
    account = make_account(item, "BANK")
    transaction = make_transaction(
        account,
        description="LANÇAMENTO DESCONHECIDO",
        amount_cents=-900,
        category=None,
        direction="DEBIT",
        description_raw=None,
    )
    banking = FakeBankingProvider(
        {item.id: (account,)}, {account.id: (transaction,)}
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    expense = expenses[0]
    assert expense.raw_category is None
    assert expense.description_raw is None
