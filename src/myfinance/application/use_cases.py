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
    CategoryPlan,
    CutSuggestion,
    HandleMessageResult,
    IdentityAnswer,
    MerchantSpend,
    MonthlyExpense,
    NeedsClarification,
    NoPluggyItem,
    ParsedMessage,
    RegisteredMessage,
    RegistrationResult,
    SpendingAnswerMessage,
    SpendingPlanMessage,
    SpendingQuery,
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
    SpendingPlanNarrator,
    SpendingQueryParser,
    SummaryIntentGate,
)
from myfinance.domain.banking import BankExpense, BankingIntent, PluggyItem
from myfinance.domain.categories import Category
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
    "GetSpendingPlanUseCase",
    "GetTopSpendingMonthUseCase",
    "HandleBankingQueryUseCase",
    "HandleMessageUseCase",
    "RegisterEntryUseCase",
    "RegisterPluggyItemUseCase",
    "SearchSpendingUseCase",
]

_EXPLANATION_TIMEOUT_SECONDS = 15
_SPENDING_SEARCH_TIMEOUT_SECONDS = 45
_SPENDING_PLAN_TIMEOUT_SECONDS = 60

_PLAN_PATTERNS = (
    r"\bplano de gastos?\b",
    r"\bplanejamento\b",
    r"\bonde\s+(?:posso\s+)?(?:cortar|diminuir|reduzir)\b",
    r"\bcomo\s+(?:posso\s+)?economizar\b",
    r"\bme\s+ajuda(?:r)?\s+a\s+economizar\b",
    r"\bdicas?\s+(?:para|de)\s+economizar\b",
    r"\breduzir\s+(?:meus\s+)?gastos\b",
    r"\bcortar\s+(?:meus\s+)?gastos\b",
)

_DISCRETIONARY_CATEGORIES = frozenset(
    {
        Category.ALIMENTACAO,
        Category.TRANSPORTE,
        Category.LAZER,
        Category.OUTROS,
    }
)

# Longest first, so "transferencia enviada pelo pix" wins over "pix".
_MERCHANT_PREFIXES = (
    "transferencia enviada pelo pix",
    "transferencia enviada",
    "compra no debito",
    "pagamento efetuado",
    "pagamento",
    "pix",
    "compra",
)

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


def _asks_for_spending_plan(text: str) -> bool:
    normalized = _strip_accents(text)
    return any(re.search(pattern, normalized) for pattern in _PLAN_PATTERNS)


def _delta_percent(current_cents: int, previous_cents: int) -> int | None:
    """Return the percentage change, or ``None`` without a previous base."""
    if previous_cents <= 0:
        return None
    return round((current_cents - previous_cents) * 100 / previous_cents)


def _clean_merchant(description: str) -> str:
    """Strip bank transaction prefixes and normalise the merchant name."""
    text = description.strip()
    if "|" in text:
        head, _, tail = text.partition("|")
        if _strip_accents(head).strip(" -") in _MERCHANT_PREFIXES:
            text = tail
    return _strip_accents(text).strip(" -|")


def _expense_items(
    entries: Sequence[Entry], bank_expenses: Sequence[BankExpense]
) -> list[tuple[date, int, Category, str]]:
    """Combine manual and bank spends, dropping forecasts and duplicates.

    A manual entry duplicates a bank expense when both share the same day and
    amount, so the bank row wins and the spend is counted once.
    """
    bank_keys = {
        (expense.day, expense.amount_cents) for expense in bank_expenses
    }
    items: list[tuple[date, int, Category, str]] = []
    for entry in entries:
        if entry.kind is EntryKind.FORECAST:
            continue
        if (entry.day, entry.amount.cents) in bank_keys:
            continue
        items.append(
            (entry.day, entry.amount.cents, entry.category, entry.description)
        )
    for expense in bank_expenses:
        items.append(
            (
                expense.day,
                expense.amount_cents,
                expense.category,
                expense.description,
            )
        )
    return items


def _distribute_cuts(
    categories: Sequence[tuple[Category, int]], target_cents: int
) -> tuple[CutSuggestion, ...]:
    """Split ``target_cents`` proportionally, forcing the sum to match it."""
    if not categories or target_cents <= 0:
        return ()
    total_cents = sum(cents for _, cents in categories)
    if total_cents <= 0:
        return ()

    cuts: list[CutSuggestion] = []
    allocated = 0
    for index, (category, cents) in enumerate(categories):
        is_last = index == len(categories) - 1
        cut_cents = (
            target_cents - allocated
            if is_last
            else round(target_cents * cents / total_cents)
        )
        allocated += cut_cents
        cuts.append(
            CutSuggestion(
                label=category.label,
                current_cents=cents,
                cut_cents=cut_cents,
            )
        )
    return tuple(cuts)


_SPENDING_QUERY_STOPWORDS = frozenset(
    {
        "quanto",
        "quantos",
        "qual",
        "quais",
        "gastei",
        "gasto",
        "gastos",
        "gaste",
        "paguei",
        "pago",
        "pagos",
        "comprei",
        "em",
        "com",
        "no",
        "na",
        "nos",
        "nas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "esse",
        "essa",
        "este",
        "esta",
        "nesse",
        "nessa",
        "neste",
        "nesta",
        "mes",
        "semana",
        "ano",
        "anos",
        "hoje",
        "ontem",
        "amanha",
        "passado",
        "passada",
        "atual",
        "ultimo",
        "ultima",
        "dia",
        "dias",
        "por",
        "para",
        "o",
        "a",
        "os",
        "as",
        "e",
        "que",
        "foi",
        "foram",
        "meu",
        "minha",
        "meus",
        "minhas",
        "eu",
        "tu",
        "voce",
        "voces",
        "ele",
        "ela",
        "eles",
        "elas",
        "gente",
        "deu",
        "deram",
        "ficou",
        "ficaram",
        "custou",
        "custaram",
        "custa",
        "custam",
        "valeu",
        "valeram",
        "saiu",
        "sairam",
        "entrou",
        "entraram",
        "sera",
        "serao",
        "vai",
        "vao",
        "vou",
        "vamos",
        "tenho",
        "tem",
        "temos",
        "tinha",
        "tinham",
        "era",
        "eram",
        "sou",
        "somos",
        "sao",
        "gastou",
        "gastaram",
        "pagou",
        "pagaram",
        "comprou",
        "compraram",
        "banco",
        "bancos",
        "conta",
        "contas",
        "cartao",
        "cartoes",
        "compras",
        "compra",
        "comprar",
        "saldo",
        "saldos",
        "extrato",
        "extratos",
        "transacao",
        "transacoes",
        "pagamento",
        "pagamentos",
        "fatura",
        "faturas",
        "pix",
        "limite",
        "credito",
        "debito",
    }
)

_MONTH_NAMES = frozenset(
    {
        "janeiro",
        "fevereiro",
        "marco",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    }
)

_TOKEN_PUNCTUATION = ".,!?;:\"'()[]{}…"

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_SPAN_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_AMOUNT_RE = re.compile(
    r"(?:R\$\s*)?(?<![\w.,/-])"
    r"(?:\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"(?!\w|[.,]\d|[-/])",
    re.IGNORECASE,
)


def _has_explicit_amount(text: str) -> bool:
    """Return whether ``text`` carries a money-like amount outside dates.

    Dates and four-digit years are masked first, so an explicit year or
    ``DD/MM`` reference never reads as a monetary value.
    """
    masked = _ISO_DATE_RE.sub(" ", text)
    masked = _DATE_SPAN_RE.sub(" ", masked)
    masked = _YEAR_RE.sub(" ", masked)
    return _AMOUNT_RE.search(masked) is not None


def _looks_like_spending_query(text: str) -> bool:
    """Return whether ``text`` asks a spending question with a concrete subject.

    Period-only questions ("quanto gastei hoje?") stay summaries, and
    registration messages without ``quanto`` never reach the spending search.
    """
    normalized = _strip_accents(text)
    if _asks_for_top_month(text):
        return False
    if not re.search(r"\bquanto\b", normalized):
        return False
    has_subject = False
    for raw in normalized.split():
        token = raw.strip(_TOKEN_PUNCTUATION)
        if not token:
            continue
        if token in _SPENDING_QUERY_STOPWORDS:
            continue
        if token in _MONTH_NAMES:
            continue
        if any(character.isdigit() for character in token):
            continue
        has_subject = True
        break
    if not has_subject:
        return False
    return not _has_explicit_amount(text)


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


class SearchSpendingUseCase:
    """Answer a free-form spending question over manual entries and the bank.

    Provider failures propagate so callers can explain them instead of
    rendering an empty answer.
    """

    def __init__(
        self,
        entries: EntryRepository,
        bank_expenses: BankExpenseProvider | None,
        clock: Clock,
        references: DateReferenceExtractor,
        dates: DateResolver,
        parser: SpendingQueryParser,
    ) -> None:
        self._entries = entries
        self._bank_expenses = bank_expenses
        self._clock = clock
        self._references = references
        self._dates = dates
        self._parser = parser

    async def execute(self, text: str) -> SpendingAnswerMessage | None:
        today = self._clock.today()
        query = await self._parser.parse(text, today=today)
        if query is None:
            return None

        start, end = self._resolve_period(
            query.period_reference or text, text, today
        )
        entries = await self._entries.list_between(start, end)
        bank_expenses: Sequence[BankExpense] = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)

        bank_keys = {
            (expense.day, expense.amount_cents) for expense in bank_expenses
        }
        amounts: list[int] = []
        for entry in entries:
            if entry.kind is EntryKind.FORECAST:
                continue
            if (entry.day, entry.amount.cents) in bank_keys:
                continue
            if self._matches(
                query,
                entry.category,
                (entry.description, entry.category.label, entry.category.value),
            ):
                amounts.append(entry.amount.cents)
        for expense in bank_expenses:
            if self._matches(
                query,
                expense.category,
                (
                    expense.description,
                    expense.category.label,
                    expense.category.value,
                    expense.raw_category or "",
                    expense.description_raw or "",
                ),
            ):
                amounts.append(expense.amount_cents)

        label = (
            query.category.label
            if query.category is not None
            else ", ".join(query.keywords)
        )
        return SpendingAnswerMessage(
            start=start,
            end=end,
            label=label,
            total_cents=sum(amounts),
            count=len(amounts),
            category=query.category,
            keywords=query.keywords,
        )

    def _resolve_period(
        self, reference: str, text: str, today: date
    ) -> tuple[date, date]:
        period = resolve_period(reference, today=today)
        if period is not None:
            return period
        extracted = self._references.extract(text)
        if extracted is not None:
            day = self._dates.resolve(extracted, today=today)
            if day is not None:
                return day, day
        return today.replace(day=1), today

    @staticmethod
    def _matches(
        query: SpendingQuery, item_category: Category, parts: Sequence[str]
    ) -> bool:
        if query.category is not None and item_category is query.category:
            return True
        haystack = _strip_accents(" ".join(parts))
        return any(
            _strip_accents(keyword) in haystack
            for keyword in query.keywords
            if keyword.strip()
        )


class GetSpendingPlanUseCase:
    """Build a grounded savings plan from the last analyzed spending window."""

    def __init__(
        self,
        entries: EntryRepository,
        bank_expenses: BankExpenseProvider | None,
        clock: Clock,
        narrator: SpendingPlanNarrator | None = None,
    ) -> None:
        self._entries = entries
        self._bank_expenses = bank_expenses
        self._clock = clock
        self._narrator = narrator

    async def execute(self, text: str = "") -> SpendingPlanMessage:
        today = self._clock.today()
        period = resolve_period(text, today=today) if text.strip() else None
        if period is None:
            last_day = today.replace(day=1) - timedelta(days=1)
            start = last_day.replace(day=1)
            end = last_day
        else:
            start, end = period

        length = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous_start = start - timedelta(days=length)

        entries = await self._entries.list_between(start, end)
        previous_entries = await self._entries.list_between(
            previous_start, previous_end
        )
        bank_expenses: Sequence[BankExpense] = ()
        previous_bank_expenses: Sequence[BankExpense] = ()
        if self._bank_expenses is not None:
            bank_expenses = await self._bank_expenses.expenses(start, end)
            previous_bank_expenses = await self._bank_expenses.expenses(
                previous_start, previous_end
            )

        items = _expense_items(entries, bank_expenses)
        previous_items = _expense_items(
            previous_entries, previous_bank_expenses
        )

        category_totals: dict[Category, int] = {}
        for _, cents, category, _ in items:
            category_totals[category] = category_totals.get(category, 0) + cents
        previous_totals: dict[Category, int] = {}
        for _, cents, category, _ in previous_items:
            previous_totals[category] = previous_totals.get(category, 0) + cents

        total_cents = sum(category_totals.values())
        previous_total_cents = sum(previous_totals.values())

        categories = tuple(
            CategoryPlan(
                category=category,
                total_cents=cents,
                share_percent=(
                    round(cents * 100 / total_cents) if total_cents else 0
                ),
                previous_cents=previous_totals.get(category, 0),
                delta_percent=_delta_percent(
                    cents, previous_totals.get(category, 0)
                ),
            )
            for category, cents in sorted(
                category_totals.items(),
                key=lambda item: (-item[1], item[0].value),
            )
        )

        grouped: dict[str, list[int]] = {}
        for _, cents, _, description in items:
            name = _clean_merchant(description)
            if not name:
                continue
            bucket = grouped.setdefault(name, [0, 0])
            bucket[0] += cents
            bucket[1] += 1
        merchants = tuple(
            MerchantSpend(name=name, total_cents=total, count=count)
            for name, (total, count) in sorted(
                grouped.items(), key=lambda item: (-item[1][0], item[0])
            )[:5]
        )

        target_cents = round(total_cents * 10 / 100)
        discretionary = sorted(
            (
                (category, cents)
                for category, cents in category_totals.items()
                if category in _DISCRETIONARY_CATEGORIES and cents > 0
            ),
            key=lambda item: (-item[1], item[0].value),
        )[:3]
        cuts = _distribute_cuts(discretionary, target_cents)

        plan = SpendingPlanMessage(
            start=start,
            end=end,
            total_cents=total_cents,
            count=len(items),
            previous_total_cents=previous_total_cents,
            categories=categories,
            merchants=merchants,
            target_cents=target_cents,
            cuts=cuts,
            narrative=None,
        )
        if self._narrator is None:
            return plan
        try:
            narrative = await self._narrator.narrate(plan)
        except ProviderError:
            narrative = None
        return replace(plan, narrative=narrative)


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
        spending_search: SearchSpendingUseCase | None = None,
        spending_plan: GetSpendingPlanUseCase | None = None,
    ) -> None:
        self._parser = parser
        self._register = register
        self._clock = clock
        self._summary = summary
        self._references = references
        self._period_summary = period_summary
        self._summary_gate = summary_gate
        self._top_month = top_month
        self._spending_search = spending_search
        self._spending_plan = spending_plan

    async def execute(self, text: str) -> HandleMessageResult:
        if self._spending_search is not None and _looks_like_spending_query(text):
            try:
                answer = await asyncio.wait_for(
                    self._spending_search.execute(text),
                    timeout=_SPENDING_SEARCH_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                raise ProviderError(
                    "A consulta de gastos demorou demais. Tente novamente."
                ) from exc
            if answer is not None:
                return answer

        if self._spending_plan is not None and _asks_for_spending_plan(text):
            try:
                return await asyncio.wait_for(
                    self._spending_plan.execute(text),
                    timeout=_SPENDING_PLAN_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                raise ProviderError(
                    "O plano de gastos demorou demais. Tente novamente."
                ) from exc

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
