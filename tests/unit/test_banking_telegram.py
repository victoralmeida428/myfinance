"""Unit tests for the Telegram banking layer (no network, no real bot)."""

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from myfinance.application.dto import (
    AccountsAnswer,
    IdentityAnswer,
    NeedsClarification,
    NoPluggyItem,
    TransactionsAnswer,
)
from myfinance.domain.banking import BankAccount, BankIdentity, BankTransaction
from myfinance.presentation.telegram.formatting import (
    format_banking,
    mask_document,
)
from myfinance.presentation.telegram.handlers import BotHandlers

TODAY = date(2026, 10, 20)
YESTERDAY = date(2026, 10, 19)
ITEM_ID = uuid4()


class InMemoryProcessedUpdates:
    def __init__(self) -> None:
        self.seen: set[int] = set()

    async def claim(self, update_id: int) -> bool:
        if update_id in self.seen:
            return False
        self.seen.add(update_id)
        return True


class FakeMessage:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeBanking:
    def __init__(
        self,
        answer: AccountsAnswer
        | TransactionsAnswer
        | IdentityAnswer
        | NoPluggyItem
        | None,
    ) -> None:
        self._answer = answer
        self.calls: list[str] = []

    async def execute(
        self, text: str
    ) -> AccountsAnswer | TransactionsAnswer | IdentityAnswer | NoPluggyItem | None:
        self.calls.append(text)
        return self._answer


class FakeManual:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, text: str) -> NeedsClarification:
        self.calls.append(text)
        return NeedsClarification("manual path")


class FakeRegisterItem:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str | None]] = []

    async def execute(
        self,
        item_id: UUID,
        *,
        status: str = "created",
        error: str | None = None,
        connector_name: str | None = None,
    ) -> None:
        assert error is None
        self.calls.append((item_id, status, connector_name))


class Unused:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("unexpected use case call")


def account(
    name: str,
    balance_cents: int,
    *,
    institution: str | None,
    account_type: str = "BANK",
) -> BankAccount:
    return BankAccount(
        id=uuid4(),
        item_id=ITEM_ID,
        type=account_type,
        name=name,
        balance_cents=balance_cents,
        currency="BRL",
        institution=institution,
    )


def transaction(day: date, description: str, amount_cents: int) -> BankTransaction:
    return BankTransaction(
        id=uuid4(),
        account_id=uuid4(),
        item_id=ITEM_ID,
        day=day,
        description=description,
        amount_cents=amount_cents,
        currency="BRL",
        category=None,
    )


def make_handlers(
    *,
    banking: FakeBanking | None = None,
    register_item: FakeRegisterItem | None = None,
    manual: FakeManual | None = None,
    updates: InMemoryProcessedUpdates | None = None,
) -> tuple[BotHandlers, FakeManual, FakeBanking | None]:
    manual = manual or FakeManual()
    handlers = BotHandlers(
        handle_message=manual,  # type: ignore[arg-type]
        summary=Unused(),  # type: ignore[arg-type]
        details=Unused(),  # type: ignore[arg-type]
        updates=updates or InMemoryProcessedUpdates(),
        banking=banking,  # type: ignore[arg-type]
        register_item=register_item,  # type: ignore[arg-type]
    )
    return handlers, manual, banking


def make_update(update_id: int, text: str | None = None):
    message = FakeMessage(text)
    update = SimpleNamespace(update_id=update_id, effective_message=message)
    return update, message


def context(args: list[str] | None = None) -> Any:
    return SimpleNamespace(args=args)


def test_format_accounts_groups_by_institution_and_keeps_negative_balance() -> None:
    answer = AccountsAnswer(
        accounts=(
            account("Conta Corrente", 123456, institution="Itaú"),
            account("Poupança", -5000, institution="Itaú"),
            account("Carteira", 0, institution=None),
        )
    )

    assert format_banking(answer) == (
        "Itaú\n"
        "- Conta Corrente (BANK): R$ 1.234,56\n"
        "- Poupança (BANK): -R$ 50,00\n"
        "\n"
        "Contas\n"
        "- Carteira (BANK): R$ 0,00"
    )


def test_format_accounts_handles_no_accounts() -> None:
    assert format_banking(AccountsAnswer(accounts=())) == "Nenhuma conta encontrada."


def test_format_transactions_for_a_single_day() -> None:
    answer = TransactionsAnswer(
        transactions=(transaction(TODAY, "Mercado", -4500),),
        start=TODAY,
        end=TODAY,
    )

    assert format_banking(answer) == (
        "Extrato de 20/10/2026\n- 20/10 Mercado: -R$ 45,00"
    )


def test_format_transactions_for_a_range() -> None:
    answer = TransactionsAnswer(
        transactions=(
            transaction(YESTERDAY, "Salário", 500000),
            transaction(TODAY, "Mercado", -4500),
        ),
        start=YESTERDAY,
        end=TODAY,
    )

    assert format_banking(answer) == (
        "Extrato de 19/10/2026 a 20/10/2026\n"
        "- 19/10 Salário: R$ 5.000,00\n"
        "- 20/10 Mercado: -R$ 45,00"
    )


def test_format_identity_masks_the_cpf() -> None:
    answer = IdentityAnswer(
        identity=BankIdentity(
            item_id=ITEM_ID,
            full_name="Maria Silva",
            document="12345678945",
            document_type="CPF",
            birth_date="1990-01-01",
        )
    )

    assert format_banking(answer) == (
        "Titular: Maria Silva\nDocumento: 123.***.***-45"
    )


def test_format_identity_handles_missing_identity() -> None:
    assert (
        format_banking(IdentityAnswer(identity=None))
        == "Dados do titular não disponíveis."
    )


def test_mask_document_handles_formatted_cpf_and_other_values() -> None:
    assert mask_document("123.456.789-45") == "123.***.***-45"
    assert mask_document("12345678000199") == "***"
    assert mask_document("") == "não informado"
    assert mask_document(None) == "não informado"


def test_format_no_pluggy_item_explains_how_to_connect() -> None:
    assert format_banking(NoPluggyItem()) == (
        "Nenhuma conta conectada. Conecte pelo Pluggy Connect e registre com "
        "/item <uuid>."
    )


async def test_banking_answer_is_replied_without_the_manual_use_case() -> None:
    banking = FakeBanking(
        AccountsAnswer(accounts=(account("Conta", 100, institution="Itaú"),))
    )
    handlers, manual, _banking = make_handlers(banking=banking)
    update, message = make_update(1, "qual meu saldo")

    await handlers.message(update, context())

    assert message.replies == ["Itaú\n- Conta (BANK): R$ 1,00"]
    assert banking is not None and banking.calls == ["qual meu saldo"]
    assert manual.calls == []


async def test_transactions_answer_is_replied() -> None:
    banking = FakeBanking(
        TransactionsAnswer(
            transactions=(transaction(TODAY, "Mercado", -4500),),
            start=TODAY,
            end=TODAY,
        )
    )
    handlers, manual, _banking = make_handlers(banking=banking)
    update, message = make_update(2, "extrato de hoje")

    await handlers.message(update, context())

    assert message.replies == ["Extrato de 20/10/2026\n- 20/10 Mercado: -R$ 45,00"]
    assert manual.calls == []


async def test_no_pluggy_item_is_replied() -> None:
    banking = FakeBanking(NoPluggyItem())
    handlers, manual, _banking = make_handlers(banking=banking)
    update, message = make_update(3, "quanto tenho na conta")

    await handlers.message(update, context())

    assert "registre com /item <uuid>" in message.replies[0]
    assert manual.calls == []


async def test_banking_none_falls_back_to_the_manual_path() -> None:
    banking = FakeBanking(None)
    handlers, manual, _banking = make_handlers(banking=banking)
    update, message = make_update(4, "Almoço hoje 45")

    await handlers.message(update, context())

    assert message.replies == ["manual path"]
    assert banking is not None and banking.calls == ["Almoço hoje 45"]
    assert manual.calls == ["Almoço hoje 45"]


async def test_duplicate_update_id_is_ignored_before_banking() -> None:
    banking = FakeBanking(NoPluggyItem())
    handlers, manual, _banking = make_handlers(banking=banking)
    update, message = make_update(5, "qual meu saldo")

    await handlers.message(update, context())
    await handlers.message(update, context())

    assert len(message.replies) == 1
    assert banking is not None and banking.calls == ["qual meu saldo"]
    assert manual.calls == []


async def test_item_command_registers_a_valid_uuid() -> None:
    register = FakeRegisterItem()
    handlers, _manual, _banking = make_handlers(register_item=register)
    update, message = make_update(6)
    item_id = uuid4()

    await handlers.item_command(update, context([str(item_id), "Itaú"]))

    assert register.calls == [(item_id, "created", "Itaú")]
    assert message.replies == [
        "Item registrado. Já pode perguntar 'qual meu saldo' ou "
        "'extrato de hoje'."
    ]


async def test_item_command_rejects_an_invalid_uuid() -> None:
    register = FakeRegisterItem()
    handlers, _manual, _banking = make_handlers(register_item=register)
    update, message = make_update(7)

    await handlers.item_command(update, context(["not-a-uuid"]))

    assert register.calls == []
    assert message.replies == ["UUID inválido."]


async def test_item_command_without_arguments_replies_invalid_uuid() -> None:
    register = FakeRegisterItem()
    handlers, _manual, _banking = make_handlers(register_item=register)
    update, message = make_update(8)

    await handlers.item_command(update, context([]))

    assert register.calls == []
    assert message.replies == ["UUID inválido."]


async def test_item_command_without_the_use_case_replies_unavailable() -> None:
    handlers, _manual, _banking = make_handlers()
    update, message = make_update(9)

    await handlers.item_command(update, context([str(uuid4())]))

    assert message.replies == ["Registro de item indisponível."]
