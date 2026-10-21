"""Data transfer objects exchanged between application and presentation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from myfinance.domain.banking import BankAccount, BankIdentity, BankTransaction
from myfinance.domain.categories import Category
from myfinance.domain.entries import Entry, EntryKind
from myfinance.domain.money import Money
from myfinance.domain.summary import CategoryBalance, DailySummary, PeriodSummary

__all__ = [
    "AccountsAnswer",
    "BankingAnswer",
    "HandleMessageResult",
    "IdentityAnswer",
    "MonthlyExpense",
    "NeedsClarification",
    "NoPluggyItem",
    "ParsedMessage",
    "RegisteredMessage",
    "RegistrationResult",
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
class SummaryMessage:
    """A message that asked for a daily or period summary instead of a registration."""

    summary: DailySummary | PeriodSummary


@dataclass(frozen=True, slots=True)
class NeedsClarification:
    """A message that could not be understood and needs a follow-up."""

    reason: str


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


type HandleMessageResult = (
    RegisteredMessage | SummaryMessage | TopMonthMessage | NeedsClarification
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
