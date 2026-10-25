"""Data transfer objects exchanged between application and presentation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeAlias

from myfinance.domain.banking import BankAccount, BankIdentity, BankTransaction
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import CategoryBalance, DailySummary, PeriodSummary

__all__ = [
    "AccountsAnswer",
    "BankingAnswer",
    "CategoryPlan",
    "ChatReply",
    "DayDetails",
    "CutSuggestion",
    "HandleMessageResult",
    "HelpMessage",
    "IdentityAnswer",
    "IncomeMessage",
    "MerchantSpend",
    "MonthlyExpense",
    "NeedsClarification",
    "NoPluggyItem",
    "ParsedMessage",
    "PeriodDetails",
    "PeriodItem",
    "RegisteredMessage",
    "RegistrationResult",
    "SpendingAnswerMessage",
    "SpendingComparisonMessage",
    "SpendingPlanMessage",
    "SpendingQuery",
    "SummaryMessage",
    "TopMonthMessage",
    "TransactionsAnswer",
]


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """Structured data extracted from a free-form user message."""

    kind: EntryKind
    amount: Money
    day: date
    category: Category
    description: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """A persisted entry together with its updated daily summary."""

    entry: Entry
    summary: DailySummary


@dataclass(frozen=True, slots=True)
class RegisteredMessage:
    """A message that parsed and was persisted successfully."""

    parsed: ParsedMessage
    result: RegistrationResult


@dataclass(frozen=True, slots=True)
class DayDetails:
    """The resolved day together with its entries."""

    day: date
    entries: Sequence[Entry]


@dataclass(frozen=True, slots=True)
class PeriodItem:
    """One realized entry or bank expense inside a period."""

    day: date
    description: str
    category: Category
    amount_cents: int
    from_bank: bool


@dataclass(frozen=True, slots=True)
class PeriodDetails:
    """Every realized entry inside an inclusive period."""

    start: date
    end: date
    items: tuple[PeriodItem, ...]


@dataclass(frozen=True, slots=True)
class SummaryMessage:
    """A message that asked for a daily or period summary instead of a registration."""

    summary: DailySummary | PeriodSummary


@dataclass(frozen=True, slots=True)
class NeedsClarification:
    """A message that could not be understood and needs a follow-up."""

    reason: str


@dataclass(frozen=True, slots=True)
class HelpMessage:
    """A request for the bot's capabilities and command reference."""


@dataclass(frozen=True, slots=True)
class IncomeMessage:
    """An income question, which the bot does not track yet."""


@dataclass(frozen=True, slots=True)
class MonthlyExpense:
    """The realized expenses of a single calendar month."""

    year: int
    month: int
    expense_cents: int


@dataclass(frozen=True, slots=True)
class TopMonthMessage:
    """The months with the highest realized spending in the window."""

    window_start: date
    window_end: date
    ranking: tuple[MonthlyExpense, ...]
    winner_balances: tuple[CategoryBalance, ...]


@dataclass(frozen=True, slots=True)
class SpendingQuery:
    """The period, category and terms extracted from a spending question."""

    period_reference: str | None
    category: Category | None
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpendingAnswerMessage:
    """The total and transaction count for a free-form spending question."""

    start: date
    end: date
    label: str
    total_cents: int
    count: int
    category: Category | None
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpendingComparisonMessage:
    """A subject compared between the current and the previous month."""

    label: str
    current_start: date
    current_end: date
    current_total_cents: int
    current_count: int
    previous_start: date
    previous_end: date
    previous_total_cents: int
    previous_count: int
    delta_cents: int
    delta_percent: int | None
    narrative: str | None = None


@dataclass(frozen=True, slots=True)
class CategoryPlan:
    """One category's spending in the analyzed window and the one before it."""

    category: Category
    total_cents: int
    share_percent: int
    previous_cents: int
    delta_percent: int | None


@dataclass(frozen=True, slots=True)
class MerchantSpend:
    """A merchant (cleaned bank description) and how much was spent there."""

    name: str
    total_cents: int
    count: int


@dataclass(frozen=True, slots=True)
class CutSuggestion:
    """A proposed cut in one discretionary category."""

    label: str
    current_cents: int
    cut_cents: int


@dataclass(frozen=True, slots=True)
class SpendingPlanMessage:
    """A grounded savings plan built from the previous window's spending."""

    start: date
    end: date
    total_cents: int
    count: int
    previous_total_cents: int
    categories: tuple[CategoryPlan, ...]
    merchants: tuple[MerchantSpend, ...]
    target_cents: int
    cuts: tuple[CutSuggestion, ...]
    narrative: str | None


HandleMessageResult: TypeAlias = (
    RegisteredMessage
    | SummaryMessage
    | TopMonthMessage
    | SpendingAnswerMessage
    | SpendingComparisonMessage
    | SpendingPlanMessage
    | NeedsClarification
    | HelpMessage
    | IncomeMessage
    | PeriodDetails
)


@dataclass(frozen=True, slots=True)
class AccountsAnswer:
    """The bank accounts connected through Pluggy."""

    accounts: Sequence[BankAccount]


@dataclass(frozen=True, slots=True)
class TransactionsAnswer:
    """The bank transactions found in the requested window."""

    transactions: Sequence[BankTransaction]
    start: date
    end: date


@dataclass(frozen=True, slots=True)
class IdentityAnswer:
    """The account holder identity, when the bank exposes it."""

    identity: BankIdentity | None


@dataclass(frozen=True, slots=True)
class NoPluggyItem:
    """No healthy Pluggy item is available to answer a banking question."""


type BankingAnswer = (
    AccountsAnswer | TransactionsAnswer | IdentityAnswer | NoPluggyItem
)

type ChatReply = BankingAnswer | HandleMessageResult
