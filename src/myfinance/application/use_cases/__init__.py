"""Application use cases."""

from __future__ import annotations

from myfinance.application.use_cases.banking import (
    HandleBankingQueryUseCase,
    RegisterPluggyItemUseCase,
)
from myfinance.application.use_cases.chat import (
    ChatUseCase,
    CreateConnectTokenUseCase,
    ExplainFailureUseCase,
)
from myfinance.application.use_cases.conversation import (
    HandleConversationMessageUseCase,
    HandleMessageUseCase,
)
from myfinance.application.use_cases.entries import (
    GetDailySummaryUseCase,
    GetDayDetailsUseCase,
    GetPeriodDetailsUseCase,
    GetPeriodSummaryUseCase,
    GetSummaryUseCase,
    RegisterEntryUseCase,
)
from myfinance.application.use_cases.insights import (
    GetTopSpendingMonthUseCase,
)
from myfinance.application.use_cases.plans import GetSpendingPlanUseCase
from myfinance.application.use_cases.spending import SearchSpendingUseCase

__all__ = [
    "ChatUseCase",
    "CreateConnectTokenUseCase",
    "ExplainFailureUseCase",
    "GetDailySummaryUseCase",
    "GetDayDetailsUseCase",
    "GetPeriodDetailsUseCase",
    "GetPeriodSummaryUseCase",
    "GetSpendingPlanUseCase",
    "GetSummaryUseCase",
    "GetTopSpendingMonthUseCase",
    "HandleBankingQueryUseCase",
    "HandleConversationMessageUseCase",
    "HandleMessageUseCase",
    "RegisterEntryUseCase",
    "RegisterPluggyItemUseCase",
    "SearchSpendingUseCase",
]
