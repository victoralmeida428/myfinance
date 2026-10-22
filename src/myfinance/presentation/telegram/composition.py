"""Composition root for the Telegram bot.

Only this module knows which infrastructure adapters implement the application
ports. Handlers receive ready-to-use use cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from myfinance.application.ports import (
    ConversationMemory,
    FollowUpResolver,
    LanguageModel,
    MessageParser,
    ProcessedUpdateRepository,
    SpendingQueryParser,
)
from myfinance.application.use_cases import (
    ExplainFailureUseCase,
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodSummaryUseCase,
    GetSpendingPlanUseCase,
    GetTopSpendingMonthUseCase,
    HandleBankingQueryUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
    RegisterPluggyItemUseCase,
    SearchSpendingUseCase,
)
from myfinance.config import Settings
from myfinance.infrastructure.categorization import (
    FallbackCategoryClassifier,
    JevCategoryClassifier,
    KeywordCategoryClassifier,
)
from myfinance.infrastructure.clock import SystemClock
from myfinance.infrastructure.opencode import OpenCodeLanguageModel
from myfinance.infrastructure.parsing.composite import CompositeMessageParser
from myfinance.infrastructure.parsing.dates import PortugueseDateResolver
from myfinance.infrastructure.parsing.deterministic import (
    DeterministicMessageParser,
)
from myfinance.infrastructure.parsing.follow_up import OpenCodeFollowUpResolver
from myfinance.infrastructure.parsing.gate import JevLLMGate
from myfinance.infrastructure.parsing.llm import OpenCodeMessageParser
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
)
from myfinance.infrastructure.parsing.spending_plan import (
    OpenCodeSpendingPlanNarrator,
)
from myfinance.infrastructure.parsing.spending_query import (
    DeterministicSpendingQueryParser,
    OpenCodeSpendingQueryParser,
)
from myfinance.infrastructure.parsing.summary_gate import JevSummaryIntentGate
from myfinance.infrastructure.pluggy_bank_expenses import (
    PluggyBankExpenseProvider,
)
from myfinance.infrastructure.pluggy_banking import PluggyBankingProvider
from myfinance.infrastructure.routing import (
    CompositeIntentRouter,
    JevIntentRouter,
    KeywordIntentRouter,
)
from myfinance.infrastructure.sqlite import (
    SqliteBankingRepository,
    SqliteConversationMemory,
    SqliteDatabase,
    SqliteEntryRepository,
    SqlitePluggyItemRepository,
    SqliteProcessedUpdateRepository,
)

__all__ = ["BotContainer", "build_container"]


@dataclass(frozen=True, slots=True)
class BotContainer:
    """Use cases and gateways the Telegram handlers need."""

    handle_message: HandleMessageUseCase
    summary: GetDailySummaryUseCase
    details: GetDayDetailsUseCase
    updates: ProcessedUpdateRepository
    period_summary: GetPeriodSummaryUseCase
    banking: HandleBankingQueryUseCase
    register_item: RegisterPluggyItemUseCase
    explain_failure: ExplainFailureUseCase | None
    memory: ConversationMemory
    follow_up: FollowUpResolver | None


def build_container(settings: Settings) -> BotContainer:
    """Wire the adapters and use cases used by the bot process."""
    clock = SystemClock(settings.timezone)
    resolver = PortugueseDateResolver()
    database = SqliteDatabase(settings.database_path)
    entries = SqliteEntryRepository(database)
    updates = SqliteProcessedUpdateRepository(database)

    keyword = KeywordCategoryClassifier()
    if _has_categorizer_token(settings):
        classifier = FallbackCategoryClassifier(
            JevCategoryClassifier(settings), keyword
        )
    else:
        classifier = keyword
    deterministic = DeterministicMessageParser(resolver, classifier)
    llm: MessageParser | None = None
    explain_failure: ExplainFailureUseCase | None = None
    model: LanguageModel | None = None
    spending_parser: SpendingQueryParser
    if _has_opencode_key(settings):
        model = OpenCodeLanguageModel(settings)
        llm = OpenCodeMessageParser(model, classifier)
        explain_failure = ExplainFailureUseCase(model)
        spending_parser = OpenCodeSpendingQueryParser(model)
    else:
        spending_parser = DeterministicSpendingQueryParser()
    parser = CompositeMessageParser(
        deterministic,
        llm,
        JevLLMGate(settings) if _has_categorizer_token(settings) else None,
    )

    register = RegisterEntryUseCase(entries, clock)
    summary_gate = (
        JevSummaryIntentGate(settings) if _has_categorizer_token(settings) else None
    )

    items = SqlitePluggyItemRepository(database)
    banking_repository = SqliteBankingRepository(database)
    provider = PluggyBankingProvider(settings)
    bank_expenses = PluggyBankExpenseProvider(provider, items, classifier)
    summary = GetDailySummaryUseCase(entries, clock, resolver, bank_expenses)
    period_summary = GetPeriodSummaryUseCase(entries, clock, bank_expenses)
    top_month = GetTopSpendingMonthUseCase(entries, bank_expenses, clock)
    keyword_intent = KeywordIntentRouter()
    jev_intent = JevIntentRouter(settings) if _has_categorizer_token(settings) else None
    router = CompositeIntentRouter(keyword_intent, jev_intent)
    register_item = RegisterPluggyItemUseCase(items, clock)
    banking = HandleBankingQueryUseCase(
        router,
        items,
        provider,
        banking_repository,
        clock,
        resolver,
        PortugueseDateReferenceExtractor(),
    )
    spending_search = SearchSpendingUseCase(
        entries,
        bank_expenses,
        clock,
        PortugueseDateReferenceExtractor(),
        resolver,
        spending_parser,
    )
    narrator = (
        OpenCodeSpendingPlanNarrator(model) if model is not None else None
    )
    spending_plan = GetSpendingPlanUseCase(
        entries,
        bank_expenses,
        clock,
        narrator,
    )

    memory = SqliteConversationMemory(database)
    follow_up = (
        OpenCodeFollowUpResolver(model)
        if _has_opencode_key(settings) and model is not None
        else None
    )

    return BotContainer(
        handle_message=HandleMessageUseCase(
            parser,
            register,
            clock,
            summary,
            PortugueseDateReferenceExtractor(),
            period_summary,
            summary_gate,
            top_month,
            spending_search,
            spending_plan,
        ),
        summary=summary,
        details=GetDayDetailsUseCase(entries, clock, resolver),
        updates=updates,
        period_summary=period_summary,
        banking=banking,
        register_item=register_item,
        explain_failure=explain_failure,
        memory=memory,
        follow_up=follow_up,
    )


def _has_opencode_key(settings: Settings) -> bool:
    """Return whether an OpenCode API key is configured for the LLM fallback."""
    secret = settings.opencode_api_key
    if secret is None:
        return False
    return bool(secret.get_secret_value().strip())


def _has_categorizer_token(settings: Settings) -> bool:
    """Return whether a TypeSafe token is configured for the Jev categorizer."""
    secret = settings.categorizer_api_token
    if secret is None:
        return False
    return bool(secret.get_secret_value().strip())
