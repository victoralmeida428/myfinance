"""Composition root for the Telegram bot.

Only this module knows which infrastructure adapters implement the application
ports. Handlers receive ready-to-use use cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from myfinance.application.ports import MessageParser, ProcessedUpdateRepository
from myfinance.application.use_cases import (
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodSummaryUseCase,
    HandleBankingQueryUseCase,
    HandleMessageUseCase,
    RegisterEntryUseCase,
    RegisterPluggyItemUseCase,
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
from myfinance.infrastructure.parsing.gate import JevLLMGate
from myfinance.infrastructure.parsing.llm import OpenCodeMessageParser
from myfinance.infrastructure.parsing.references import (
    PortugueseDateReferenceExtractor,
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
    if _has_opencode_key(settings):
        llm = OpenCodeMessageParser(OpenCodeLanguageModel(settings), classifier)
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

    return BotContainer(
        handle_message=HandleMessageUseCase(
            parser,
            register,
            clock,
            summary,
            PortugueseDateReferenceExtractor(),
            period_summary,
            summary_gate,
        ),
        summary=summary,
        details=GetDayDetailsUseCase(entries, clock, resolver),
        updates=updates,
        period_summary=period_summary,
        banking=banking,
        register_item=register_item,
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
