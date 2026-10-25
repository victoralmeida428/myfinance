"""Composition root for the Telegram bot.

Only this module knows which infrastructure adapters implement the application
ports. Handlers receive the conversation and the command use cases ready to use.
"""

from __future__ import annotations

from dataclasses import dataclass

from myfinance.application.ports import (
    ConversationMemory,
    FollowUpResolver,
    LanguageModel,
    ProcessedUpdateRepository,
    SpendingQueryParser,
)
from myfinance.application.use_cases import (
    ExplainFailureUseCase,
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodDetailsUseCase,
    GetPeriodSummaryUseCase,
    GetSpendingPlanUseCase,
    GetSummaryUseCase,
    GetTopSpendingMonthUseCase,
    HandleBankingQueryUseCase,
    HandleConversationMessageUseCase,
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
from myfinance.infrastructure.pluggy_bank_expenses import (
    PluggyBankExpenseProvider,
)
from myfinance.infrastructure.pluggy_banking import PluggyBankingProvider
from myfinance.infrastructure.routing import (
    CompositeIntentRouter,
    CompositeMessageIntentRouter,
    JevIntentRouter,
    JevMessageIntentRouter,
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
from myfinance.presentation.telegram.conversation import TelegramConversation

__all__ = [
    "BotContainer",
    "build_container",
    "build_follow_up_resolver",
    "build_spending_parser",
]


@dataclass(frozen=True, slots=True)
class BotContainer:
    """Entry points the Telegram handlers need."""

    conversation: TelegramConversation
    summary: GetSummaryUseCase
    details: GetDayDetailsUseCase
    updates: ProcessedUpdateRepository
    register_item: RegisterPluggyItemUseCase


def build_container(settings: Settings) -> BotContainer:
    """Wire the adapters and use cases used by the bot process."""
    clock = SystemClock(settings.timezone)
    resolver = PortugueseDateResolver()
    database = SqliteDatabase(settings.database_path)
    entries = SqliteEntryRepository(database)
    updates = SqliteProcessedUpdateRepository(database)

    classifier = _build_classifier(settings)
    model = _build_model(settings)
    explain_failure = ExplainFailureUseCase(model) if model is not None else None

    parser = CompositeMessageParser(
        DeterministicMessageParser(resolver, classifier),
        OpenCodeMessageParser(model, classifier) if model is not None else None,
        JevLLMGate(settings) if _has_categorizer_token(settings) else None,
    )

    register = RegisterEntryUseCase(entries, clock)
    classifier = (
        JevMessageIntentRouter(settings)
        if _has_categorizer_token(settings)
        else None
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
    banking_router = CompositeIntentRouter(keyword_intent, jev_intent)
    message_router = CompositeMessageIntentRouter(
        keyword_intent, jev_intent, classifier=classifier
    )

    register_item = RegisterPluggyItemUseCase(items, clock)
    banking = HandleBankingQueryUseCase(
        banking_router,
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
        build_spending_parser(settings, model),
    )
    spending_plan = GetSpendingPlanUseCase(
        entries,
        bank_expenses,
        clock,
        OpenCodeSpendingPlanNarrator(model) if model is not None else None,
    )
    period_details = GetPeriodDetailsUseCase(
        entries,
        bank_expenses,
        clock,
        PortugueseDateReferenceExtractor(),
        resolver,
    )
    messages = HandleMessageUseCase(
        message_router,
        parser,
        register,
        clock,
        summary,
        PortugueseDateReferenceExtractor(),
        period_summary,
        top_month,
        spending_search,
        spending_plan,
        period_details,
    )

    memory = SqliteConversationMemory(database)
    follow_up = build_follow_up_resolver(settings, model)

    return BotContainer(
        conversation=TelegramConversation(
            incoming=HandleConversationMessageUseCase(
                message_router, banking, messages
            ),
            memory=memory,
            follow_up=follow_up,
            explain_failure=explain_failure,
        ),
        summary=GetSummaryUseCase(period_summary, summary),
        details=GetDayDetailsUseCase(entries, clock, resolver),
        updates=updates,
        register_item=register_item,
    )


def build_spending_parser(
    settings: Settings, model: LanguageModel | None
) -> SpendingQueryParser:
    """Choose the LLM parser when a model is configured, else the fallback."""
    if model is not None and _has_opencode_key(settings):
        return OpenCodeSpendingQueryParser(model)
    return DeterministicSpendingQueryParser()


def build_follow_up_resolver(
    settings: Settings, model: LanguageModel | None
) -> FollowUpResolver | None:
    """Build the follow-up resolver only when a language model is available."""
    if model is None or not _has_opencode_key(settings):
        return None
    return OpenCodeFollowUpResolver(model)


def _build_classifier(
    settings: Settings,
) -> KeywordCategoryClassifier | FallbackCategoryClassifier:
    keyword = KeywordCategoryClassifier()
    if _has_categorizer_token(settings):
        return FallbackCategoryClassifier(
            JevCategoryClassifier(settings), keyword
        )
    return keyword


def _build_model(settings: Settings) -> LanguageModel | None:
    if not _has_opencode_key(settings):
        return None
    return OpenCodeLanguageModel(settings)


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
