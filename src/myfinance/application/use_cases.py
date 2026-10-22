"""Application use cases."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

from myfinance.application.dto import (
    AccountsAnswer,
    BankingAnswer,
    HandleMessageResult,
    IdentityAnswer,
    MonthlyExpense,
    NeedsClarification,
    NoPluggyItem,
    ParsedMessage,
    RegisteredMessage,
    RegistrationResult,
    SummaryMessage,
    TopMonthMessage,
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
from myfinance.domain.entries import Entry, EntryKind
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
    "ExplainFailureUseCase",
    "GetDailySummaryUseCase",
    "GetDayDetailsUseCase",
    "GetPeriodSummaryUseCase",
    "GetTopSpendingMonthUseCase",
    "HandleBankingQueryUseCase",
    "HandleMessageUseCase",
    "RegisterEntryUseCase",
    "RegisterPluggyItemUseCase",
]

_EXPLANATION_TIMEOUT_SECONDS = 15

_EXPLANATION_SYSTEM_PROMPT = (
    "Você é um assistente financeiro pessoal. Responda em português do "
    "Brasil, em no máximo três frases. Diga que não foi possível concluir o "
    "pedido, explique a causa em linguagem simples, repita brevemente o que "
    "a pessoa pediu e sugira tentar novamente. Nunca invente valores ou "
    "lançamentos e nunca exponha tokens, URLs ou detalhes técnicos."
)

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

_TOP_MONTH_PATTERNS = (
    r"\bqual\b.*\bmes\b.*\bmais\b.*\b(gastei|gasto|gastos)\b",
    r"\bqual\b.*\bmes\b.*\b(gastei|gasto|gastos)\b.*\bmais\b",
    r"\bmes\b.*\bmais\b.*\b(gastei|gasto|gastos)\b",
    r"\bmes com mais gastos\b",
    r"\bmaior gasto\b",
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


def _asks_for_top_month(text: str) -> bool:
    normalized = _strip_accents(text)
    return any(re.search(pattern, normalized) for pattern in _TOP_MONTH_PATTERNS)


def _shift_month(first_day: date, delta: int) -> date:
    """Return the first day of the calendar month ``delta`` months away."""
    index = first_day.year * 12 + (first_day.month - 1) + delta
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


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


class ExplainFailureUseCase:
    """Ask the language model to explain a failed request in plain Portuguese."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    async def execute(self, *, question: str, error: Exception) -> str:
        messages = (
            ChatMessage(role="system", content=_EXPLANATION_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"Pedido do usuário: {question}\n"
                    f"Falha: {type(error).__name__}: {error}"
                ),
            ),
        )
        try:
            text = await asyncio.wait_for(
                self._model.complete(messages),
                timeout=_EXPLANATION_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise ProviderError(
                "A explicação do erro demorou demais."
            ) from exc
        explanation = text.strip()
        if not explanation:
            raise ProviderError("O modelo não explicou a falha.")
        return explanation


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
    """Return the daily summary for a referenced day.

    Provider failures propagate so callers can explain them instead of
    rendering an empty day.
    """

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
            bank_expenses = await self._bank_expenses.expenses(day, day)
        return build_daily_summary(day, entries, bank_expenses)

    def _resolve(self, reference: str | None) -> date:
        today = self._clock.today()
        day = self._resolver.resolve(reference, today=today)
        if day is None:
            raise InvalidDateReference("Não entendi a data informada.")
        return day


class GetPeriodSummaryUseCase:
    """Return the summary of the period named by a reference, when recognised.

    Provider failures propagate so callers can explain them instead of
    rendering an empty period.
    """

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
            bank_expenses = await self._bank_expenses.expenses(start, end)
        return build_period_summary(start, end, entries, bank_expenses)


class GetTopSpendingMonthUseCase:
    """Rank the last months by realized spending and return the top month."""

    def __init__(
        self,
        repository: EntryRepository,
        bank_expenses: BankExpenseProvider,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._bank_expenses = bank_expenses
        self._clock = clock

    async def execute(self, months: int = 12) -> TopMonthMessage:
        today = self._clock.today()
        start = _shift_month(today.replace(day=1), -(months - 1))
        entries = await self._repository.list_between(start, today)
        bank = await self._bank_expenses.expenses(start, today)

        bank_keys = {
            (expense.day, expense.amount_cents) for expense in bank
        }
        totals: dict[tuple[int, int], int] = {}
        for entry in entries:
            if entry.kind is EntryKind.FORECAST:
                continue
            if (entry.day, entry.amount.cents) in bank_keys:
                continue
            key = (entry.day.year, entry.day.month)
            totals[key] = totals.get(key, 0) + entry.amount.cents
        for expense in bank:
            key = (expense.day.year, expense.day.month)
            totals[key] = totals.get(key, 0) + expense.amount_cents

        ranking = tuple(
            MonthlyExpense(
                year=year, month=month, expense_cents=expense_cents
            )
            for (year, month), expense_cents in sorted(
                totals.items(), key=lambda item: (-item[1], item[0])
            )
            if expense_cents > 0
        )[:3]

        if not ranking:
            return TopMonthMessage(
                window_start=start,
                window_end=today,
                ranking=(),
                winner_balances=(),
            )

        winner = ranking[0]
        month_start = date(winner.year, winner.month, 1)
        next_month_start = _shift_month(month_start, 1)
        is_current_month = (
            winner.year == today.year and winner.month == today.month
        )
        month_end = today if is_current_month else next_month_start - timedelta(days=1)
        summary = build_period_summary(
            month_start,
            month_end,
            tuple(
                entry
                for entry in entries
                if month_start <= entry.day <= month_end
            ),
            tuple(
                expense
                for expense in bank
                if month_start <= expense.day <= month_end
            ),
        )
        return TopMonthMessage(
            window_start=start,
            window_end=today,
            ranking=ranking,
            winner_balances=summary.balances,
        )


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
        top_month: GetTopSpendingMonthUseCase | None = None,
    ) -> None:
        self._parser = parser
        self._register = register
        self._clock = clock
        self._summary = summary
        self._references = references
        self._period_summary = period_summary
        self._summary_gate = summary_gate
        self._top_month = top_month

    async def execute(self, text: str) -> HandleMessageResult:
        decision = None
        if self._summary_gate is not None:
            try:
                decision = await self._summary_gate.should_summarize(text)
            except ProviderError:
                decision = None
        wants_summary = decision if decision is not None else _asks_for_summary(text)
        if wants_summary:
            if self._top_month is not None and _asks_for_top_month(text):
                try:
                    return await asyncio.wait_for(
                        self._top_month.execute(), timeout=45
                    )
                except TimeoutError as exc:
                    raise ProviderError(
                        "A consulta de meses demorou demais. Tente novamente."
                    ) from exc
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
