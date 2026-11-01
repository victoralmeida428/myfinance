"""Unit tests for the Pluggy bank-expense adapter (no network, no database)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from myfinance.application.errors import ProviderError
from myfinance.domain.banking import (
    BankAccount,
    BankIdentity,
    BankTransaction,
    PluggyItem,
)
from myfinance.domain.categories import Category
from myfinance.infrastructure.pluggy_bank_expenses import (
    PluggyBankExpenseProvider,
)

TODAY = date(2026, 10, 20)
HOLDER = "Alexsander de Souza de Almeida"
DOCUMENT = "024.934.827-60"


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
        identities: dict[UUID, BankIdentity | Exception | None] | None = None,
    ) -> None:
        self._accounts = accounts
        self._transactions = transactions
        self._identities = identities or {}
        self.transaction_calls: list[UUID] = []

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]:
        return self._accounts.get(item_id, ())

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]:
        self.transaction_calls.append(account_id)
        return self._transactions.get(account_id, ())

    async def find_identity(self, item_id: UUID) -> BankIdentity | None:
        identity = self._identities.get(item_id)
        if isinstance(identity, Exception):
            raise identity
        return identity


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


def make_identity(
    item: PluggyItem,
    *,
    full_name: str = HOLDER,
    document: str = DOCUMENT,
) -> BankIdentity:
    return BankIdentity(
        item_id=item.id,
        full_name=full_name,
        document=document,
        document_type="CPF",
        birth_date=None,
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
    day: date = TODAY,
    description_raw: str | None = None,
) -> BankTransaction:
    return BankTransaction(
        id=uuid4(),
        account_id=account.id,
        item_id=account.item_id,
        day=day,
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


def build_single_account(
    *,
    identity: BankIdentity | Exception | None = None,
    holder: bool = False,
) -> tuple[
    PluggyItem,
    BankAccount,
    dict[UUID, BankIdentity | Exception | None],
    dict[UUID, Sequence[BankAccount]],
]:
    item = make_item("Banco")
    account = make_account(item, "BANK")
    if holder:
        identity = make_identity(item)
    identities = {item.id: identity} if identity is not None else {}
    return item, account, identities, {item.id: (account,)}


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
    provider = build_provider(items=(bank_item, card_item), banking=banking)

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


async def test_credit_card_payment_and_investments_are_excluded() -> None:
    item, account, identities, accounts = build_single_account()
    transactions = tuple(
        make_transaction(
            account,
            description=description,
            amount_cents=-1000,
            category=category,
            direction="DEBIT",
        )
        for description, category in (
            ("Pagamento de fatura", "Credit card payment"),
            ("Aplicação", "Investments"),
        )
    )
    banking = FakeBankingProvider(
        accounts, {account.id: transactions}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_same_person_transfer_is_excluded_without_a_pair() -> None:
    item, account, identities, accounts = build_single_account()
    transaction = make_transaction(
        account,
        description="DEB PIX CHAVE",
        amount_cents=-2000,
        category="Same person transfer",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (transaction,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_holder_name_on_a_transfer_is_excluded_without_a_pair() -> None:
    item, account, identities, accounts = build_single_account(holder=True)
    transaction = make_transaction(
        account,
        description="PIX ENVIADO - DES Alexsander de Souza d 28/10",
        amount_cents=-1000,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (transaction,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_transfer_to_another_registered_account_is_excluded_by_pairing() -> None:
    source_item = make_item("Bradesco")
    target_item = make_item("Mercado Pago")
    source = make_account(source_item, "BANK")
    target = make_account(target_item, "BANK")
    debit = make_transaction(
        source,
        description="DEB PIX CHAVE",
        amount_cents=-1000,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    credit = make_transaction(
        target,
        description="Pix recebido ALEXSANDER DE SOUZA DE ALMEIDA",
        amount_cents=1000,
        category="Same person transfer",
        direction="CREDIT",
    )
    banking = FakeBankingProvider(
        {source_item.id: (source,), target_item.id: (target,)},
        {source.id: (debit,), target.id: (credit,)},
        {
            source_item.id: make_identity(source_item),
            target_item.id: make_identity(target_item),
        },
    )
    provider = build_provider(items=(source_item, target_item), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_credit_card_payment_pairs_with_the_card_account() -> None:
    item = make_item("Bradesco")
    bank = make_account(item, "BANK")
    card = make_account(item, "CREDIT", "GOL SMILES")
    debit = make_transaction(
        bank,
        description="Pagamento de fatura Cartão de crédito",
        amount_cents=-3385_37,
        category="Transfers",
        direction="DEBIT",
    )
    credit = make_transaction(
        card,
        description="Pagamento recebido",
        amount_cents=-3385_37,
        category="Credit card payment",
        direction="CREDIT",
    )
    banking = FakeBankingProvider(
        {item.id: (bank, card)},
        {bank.id: (debit,), card.id: (credit,)},
        {item.id: make_identity(item)},
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_card_payment_without_a_registered_card_account_counts() -> None:
    item, account, identities, accounts = build_single_account()
    debit = make_transaction(
        account,
        description="Pagamento de fatura Cartão de crédito",
        amount_cents=-1022_67,
        category="Transfers",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (debit,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [debit.id]


async def test_pairing_requires_the_same_holder() -> None:
    source_item = make_item("Bradesco")
    target_item = make_item("Mercado Pago")
    source = make_account(source_item, "BANK")
    target = make_account(target_item, "BANK")
    debit = make_transaction(
        source,
        description="DEB PIX CHAVE",
        amount_cents=-1000,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    credit = make_transaction(
        target,
        description="Pix recebido ALEXSANDER DE SOUZA DE ALMEIDA",
        amount_cents=1000,
        category="Same person transfer",
        direction="CREDIT",
    )
    banking = FakeBankingProvider(
        {source_item.id: (source,), target_item.id: (target,)},
        {source.id: (debit,), target.id: (credit,)},
        {
            source_item.id: make_identity(source_item),
            target_item.id: make_identity(
                target_item,
                full_name="Maria Silva",
                document="111.111.111-11",
            ),
        },
    )
    provider = build_provider(items=(source_item, target_item), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [debit.id]


async def test_pairing_accepts_a_credit_inside_the_window() -> None:
    source_item = make_item("Bradesco")
    target_item = make_item("Mercado Pago")
    source = make_account(source_item, "BANK")
    target = make_account(target_item, "BANK")
    debit = make_transaction(
        source,
        description="DEB PIX CHAVE",
        amount_cents=-1000,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    credit = make_transaction(
        target,
        description="Pix recebido ALEXSANDER DE SOUZA DE ALMEIDA",
        amount_cents=1000,
        category="Same person transfer",
        direction="CREDIT",
        day=TODAY + timedelta(days=2),
    )
    banking = FakeBankingProvider(
        {source_item.id: (source,), target_item.id: (target,)},
        {source.id: (debit,), target.id: (credit,)},
        {
            source_item.id: make_identity(source_item),
            target_item.id: make_identity(target_item),
        },
    )
    provider = build_provider(items=(source_item, target_item), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_pairing_ignores_a_credit_outside_the_window() -> None:
    source_item = make_item("Bradesco")
    target_item = make_item("Mercado Pago")
    source = make_account(source_item, "BANK")
    target = make_account(target_item, "BANK")
    debit = make_transaction(
        source,
        description="DEB PIX CHAVE",
        amount_cents=-1000,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    credit = make_transaction(
        target,
        description="Pix recebido ALEXSANDER DE SOUZA DE ALMEIDA",
        amount_cents=1000,
        category="Same person transfer",
        direction="CREDIT",
        day=TODAY + timedelta(days=4),
    )
    banking = FakeBankingProvider(
        {source_item.id: (source,), target_item.id: (target,)},
        {source.id: (debit,), target.id: (credit,)},
        {
            source_item.id: make_identity(source_item),
            target_item.id: make_identity(target_item),
        },
    )
    provider = build_provider(items=(source_item, target_item), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [debit.id]


async def test_unpaired_third_party_transfer_counts() -> None:
    item, account, identities, accounts = build_single_account(holder=True)
    transaction = make_transaction(
        account,
        description="PIX ENVIADO - DES Ana Deborah da Silva",
        amount_cents=-500,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (transaction,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [transaction.id]


async def test_bill_payment_counts() -> None:
    item, account, identities, accounts = build_single_account()
    transaction = make_transaction(
        account,
        description="PAGAMENTO DE BOLETO",
        amount_cents=-4618_78,
        category="Transfer - Bank Slip",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (transaction,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [transaction.id]


async def test_internal_transfer_is_excluded() -> None:
    item, account, identities, accounts = build_single_account()
    transaction = make_transaction(
        account,
        description="Dinheiro reservado Férias",
        amount_cents=-2547_64,
        category="Transfer - Internal",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (transaction,)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert expenses == ()


async def test_cash_withdrawal_counts_even_when_paired() -> None:
    item, account, identities, accounts = build_single_account()
    target = make_account(item, "BANK", "Poupança")
    accounts[item.id] = (account, target)
    debit = make_transaction(
        account,
        description="SAQUE BANCO 24H",
        amount_cents=-120,
        category="Same person transfer - CASH",
        direction="DEBIT",
    )
    credit = make_transaction(
        target,
        description="Pix recebido ALEXSANDER DE SOUZA DE ALMEIDA",
        amount_cents=120,
        category="Same person transfer",
        direction="CREDIT",
    )
    banking = FakeBankingProvider(
        accounts,
        {account.id: (debit,), target.id: (credit,)},
        {item.id: make_identity(item)},
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [debit.id]


async def test_identity_lookup_failure_does_not_break_the_summary() -> None:
    item, account, identities, accounts = build_single_account(
        identity=ProviderError("identity unavailable")
    )
    same_person = make_transaction(
        account,
        description="DEB PIX CHAVE",
        amount_cents=-1000,
        category="Same person transfer",
        direction="DEBIT",
    )
    third_party = make_transaction(
        account,
        description="PIX ENVIADO - DES Ana Deborah da Silva",
        amount_cents=-500,
        category="Transfer - PIX",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (same_person, third_party)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert [expense.id for expense in expenses] == [third_party.id]


async def test_similar_category_names_are_not_treated_as_transfers() -> None:
    item, account, identities, accounts = build_single_account()
    taxes = make_transaction(
        account,
        description="Imposto sobre investimentos",
        amount_cents=-100,
        category="Taxes on investments",
        direction="DEBIT",
    )
    fees = make_transaction(
        account,
        description="Tarifa de transferência",
        amount_cents=-200,
        category="Wire transfer fees and ATM fees",
        direction="DEBIT",
    )
    banking = FakeBankingProvider(
        accounts, {account.id: (taxes, fees)}, identities
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(TODAY, TODAY)

    assert {expense.id for expense in expenses} == {taxes.id, fees.id}


async def test_credit_card_payment_that_crosses_the_month_is_paired() -> None:
    item = make_item("Bradesco")
    bank = make_account(item, "BANK")
    card = make_account(item, "CREDIT", "GOL SMILES")
    debit = make_transaction(
        bank,
        description="Pagamento de fatura",
        amount_cents=-3385_37,
        category="Transfers",
        direction="DEBIT",
        day=date(2026, 10, 31),
    )
    credit = make_transaction(
        card,
        description="Pagamento recebido",
        amount_cents=-3385_37,
        category="Credit card payment",
        direction="CREDIT",
        day=date(2026, 11, 1),
    )
    banking = FakeBankingProvider(
        {item.id: (bank, card)},
        {bank.id: (debit,), card.id: (credit,)},
        {item.id: make_identity(item)},
    )
    provider = build_provider(items=(item,), banking=banking)

    expenses = await provider.expenses(date(2026, 10, 1), date(2026, 10, 31))

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
