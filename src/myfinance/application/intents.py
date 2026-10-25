"""Message intent vocabulary shared by routing and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from myfinance.domain.banking import BankingIntent

__all__ = ["MessageIntent", "RoutingDecision"]


class MessageIntent(StrEnum):
    """The kind of answer an incoming message should produce."""

    BANKING = "banking"
    SPENDING_SEARCH = "spending_search"
    SPENDING_COMPARISON = "spending_comparison"
    SPENDING_PLAN = "spending_plan"
    TOP_MONTH = "top_month"
    SUMMARY = "summary"
    REGISTER = "register"
    HELP = "help"
    INCOME = "income"
    PERIOD_DETAILS = "period_details"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The intent chosen for a message and, for banking, its subtype."""

    intent: MessageIntent
    banking_intent: BankingIntent | None = None
