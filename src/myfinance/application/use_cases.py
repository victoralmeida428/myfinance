"""Application use cases."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from uuid import UUID, uuid4

from myfinance.application.dto import (
    AccountsAnswer,
    BankingAnswer,
    HandleMessageResult,
    IdentityAnswer,
    NeedsClarification,
    NoPluggyItem,
    ParsedMessage,
    RegisteredMessage,
    RegistrationResult,
    SummaryMessage,
    TransactionsAnswer,
)
from myfinance.application.errors import InvalidDateReference, ProviderError
from myfinance.application.periods import resolve_period
from myfinance.application.ports import (
    BankExpenseProvider,
    BankingProvider,
    BankingRepository,
    Clock,
    ConnectTokenProvider,
    DateReferenceExtractor,
    DateResolver,
    EntryRepository,
    IntentRouter,
    LanguageModel,
    MessageParser,
    PluggyItemRepository,
    SummaryIntentGate,
)
from myfinance.domain.banking import BankingIntent, PluggyItem
from myfinance.domain.entries import Entry
from myfinance.domain.models import ChatMessage, ClientUserId, ConnectToken
from myfinance.domain.summary import (
    DailySummary,
    PeriodSummary,
    build_daily_summary,
    build_period_summary,
)

__all__ = [
    "ChatUseCase",
    "CreateConnectTokenUseCase",
    "GetDailySummaryUseCase",
    "GetDayDetailsUseCase",
    "GetPeriodSummaryUseCase",
    "HandleBankingQueryUseCase",
    "HandleMessageUseCase",
    "RegisterEntryUseCase",
    "RegisterPluggyItemUseCase",
]

_SUMMARY_PATTERNS = (
    r"\bresumo\b",
    r"\bresume\b",
    r"\bbalanco\b",
    r"\bcomo (estao|esta)\b.*\bgastos?\b",
    r"\bmeus gastos\b",
    r"\bquanto\b.*\b(gastei|gastos?|gaste|gasto)\b",
    r"\bquanto\b.*\b(planejei|tenho)\b",
    r"\bgastos (de|do|da|desse|deste|nesse|neste)\b",
)


def _strip_accents(text: str) -> str:
    """Lowercase a free-form sentence and remove its accents, using stdlib only."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def _asks_for_summary(text: str) -> bool:
    normalized = _strip_accents(text)
    return any(re.search(pattern, normalized) for pattern in _SUMMARY_PATTERNS)


class CreateConnectTokenUseCase:
    """Validate the client user id and obtain a connect token."""

    def __init__(self, provider: ConnectTokenProvider) -> None:
        self._provider = provider

    async def execute(self, client_user_id: str) -> ConnectToken:
        return await self._provider.create_connect_token(ClientUserId(client_user_id))


class ChatUseCase:
    """Complete a chat conversation through a language model."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def execute(
        self,
        messages: Sequence[ChatMessage],
        *,
        session_id: str | None = None,
    ) -> str:
        return await self._model.complete(messages, session_id=session_id)


class RegisterEntryUseCase:
    """Persist a parsed entry and return the updated daily summary."""

    def __init__(self, repository: EntryRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def execute(self, parsed: ParsedMessage) -> RegistrationResult:
        entry = Entry(
            id=uuid4(),
            kind=parsed.kind,
            day=parsed.day,
            amount=parsed.amount,
            description=parsed.description,
            category=parsed.category,
            created_at=self._clock.now(),
        )
        await self._repository.add(entry)
        entries = await self._repository.list_by_day(parsed.day)
        summary = build_daily_summary(parsed.day, entries)
        return RegistrationResult(entry=entry, summary=summary)


class GetDailySummaryUseCase:
    """Return the daily summary for a referenced day."""

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        resolver: DateResolver,
        bank_expenses: BankExpenseProvider | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._resolver = resolver
        self._bank_expenses = bank_expenses

    async def execute(self, reference: str | None = None) -> DailySummary:
        day = self._resolve(reference)
        entries = await self._repository.list_by_day(day)
        bank_expenses = ()
        if self._bank_expenses is not None:
            try:
                bank_expenses = await self._bank_expenses.expenses(day, day)
            except ProviderError:
                bank_expenses = ()
        return build_daily_summary(day, entries, bank_expenses)

    def _resolve(self, reference: str | None) -> date:
        today = self._clock.today()
        day = self._resolver.resolve(reference, today=today)
        if day is None:
            raise InvalidDateReference("Não entendi a data informada.")
        return day


class GetPeriodSummaryUseCase:
    """Return the summary of the period named by a reference, when recognised."""

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        bank_expenses: BankExpenseProvider | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._bank_expenses = bank_expenses

    async def execute(self, reference: str | None) -> PeriodSummary | None:
        period = resolve_period(reference, today=self._clock.today())
        if period is None:
            return None
        start, end = period
        entries = await self._repository.list_between(start, end)
        bank_expenses = ()
        if self._bank_expenses is not None:
            try:
                bank_expenses = await self._bank_expenses.expenses(start, end)
            except ProviderError:
                bank_expenses = ()
        return build_period_summary(start, end, entries, bank_expenses)


class GetDayDetailsUseCase:
    """Return every entry registered for a referenced day."""

    def __init__(
        self,
        repository: EntryRepository,
        clock: Clock,
        resolver: DateResolver,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._resolver = resolver

    async def execute(self, reference: str | None = None) -> Sequence[Entry]:
        today = self._clock.today()
        day = self._resolver.resolve(reference, today=today)
        if day is None:
            raise InvalidDateReference("Não entendi a data informada.")
        return await self._repository.list_by_day(day)


class HandleMessageUseCase:
    """Parse a user message and register the resulting entry."""

    def __init__(
        self,
        parser: MessageParser,
        register: RegisterEntryUseCase,
        clock: Clock,
        summary: GetDailySummaryUseCase,
        references: DateReferenceExtractor,
        period_summary: GetPeriodSummaryUseCase | None = None,
        summary_gate: SummaryIntentGate | None = None,
    ) -> None:
        self._parser = parser
        self._register = register
        self._clock = clock
        self._summary = summary
        self._references = references
        self._period_summary = period_summary
        self._summary_gate = summary_gate

    async def execute(self, text: str) -> HandleMessageResult:
        decision = None
        if self._summary_gate is not None:
            try:
                decision = await self._summary_gate.should_summarize(text)
            except ProviderError:
                decision = None
        wants_summary = decision if decision is not None else _asks_for_summary(text)
        if wants_summary:
            if self._period_summary is not None:
                period = await self._period_summary.execute(text)
                if period is not None:
                    return SummaryMessage(summary=period)
            reference = self._references.extract(text)
            summary = await self._summary.execute(reference)
            return SummaryMessage(summary=summary)

        parsed = await self._parser.parse(text, today=self._clock.today())
        if parsed is None:
            return NeedsClarification(
                "Não consegui identificar valor e data. "
                "Tente algo como: almoço hoje 45."
            )
        return RegisteredMessage(parsed=parsed, result=await self._register.execute(parsed))


class RegisterPluggyItemUseCase:
    """Record the latest state of the linked Pluggy item."""

    def __init__(self, items: PluggyItemRepository, clock: Clock) -> None:
        self._items = items
        self._clock = clock

    async def execute(
        self,
        item_id: UUID,
        *,
        status: str = "created",
        error: str | None = None,
        connector_name: str | None = None,
    ) -> PluggyItem:
        item = PluggyItem(
            id=item_id,
            status=status,
            error=error,
            updated_at=self._clock.now(),
            connector_name=connector_name,
        )
        await self._items.upsert(item)
        return item


class HandleBankingQueryUseCase:
    """Answer a banking question about the connected account, when possible."""

    def __init__(
        self,
        router: IntentRouter,
        items: PluggyItemRepository,
        provider: BankingProvider,
        banking: BankingRepository,
        clock: Clock,
        dates: DateResolver,
        references: DateReferenceExtractor,
    ) -> None:
        self._router = router
        self._items = items
        self._provider = provider
        self._banking = banking
        self._clock = clock
        self._dates = dates
        self._references = references

    async def execute(self, text: str) -> BankingAnswer | None:
        intent = await self._router.route(text)
        if intent is BankingIntent.NONE:
            return None

        items = await self._items.list_active()
        if not items:
            return NoPluggyItem()

        if intent is BankingIntent.ACCOUNTS:
            accounts = []
            for item in items:
                item_accounts = await self._provider.list_accounts(item.id)
                accounts.extend(
                    replace(account, institution=item.connector_name)
                    for account in item_accounts
                )
            await self._banking.save_accounts(accounts)
            return AccountsAnswer(accounts=accounts)

        if intent is BankingIntent.TRANSACTIONS:
            start, end = self._window(text)
            transactions = []
            for item in items:
                item_accounts = await self._provider.list_accounts(item.id)
                for account in item_accounts:
                    if account.type != "BANK":
                        continue
                    transactions.extend(
                        await self._provider.list_transactions(
                            account.id, start=start, end=end
                        )
                    )
            await self._banking.save_transactions(transactions)
            return TransactionsAnswer(
                transactions=transactions, start=start, end=end
            )

        identity = None
        for item in items:
            found = await self._provider.find_identity(item.id)
            if found is not None:
                identity = found
                break
        if identity is not None:
            await self._banking.save_identity(identity)
        return IdentityAnswer(identity=identity)

    def _window(self, text: str) -> tuple[date, date]:
        today = self._clock.today()
        reference = self._references.extract(text)
        day = self._dates.resolve(reference, today=today) or today
        if "mes" in _strip_accents(text):
            return today.replace(day=1), today
        return day, day
