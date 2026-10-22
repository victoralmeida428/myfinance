"""Banking domain types.

Pure data: no I/O and no dependency on the framework or on the Pluggy SDK.
Monetary values are always integer cents so that no float ever represents
money inside the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from myfinance.domain.categories import Category
from myfinance.domain.exceptions import InvalidAmount

__all__ = [
    "BankAccount",
    "BankExpense",
    "BankIdentity",
    "BankTransaction",
    "BankingIntent",
    "PluggyItem",
    "to_cents",
]

_CENT = Decimal("0.01")


class BankingIntent(StrEnum):
    """What the user is asking about the connected bank account."""

    ACCOUNTS = "accounts"
    TRANSACTIONS = "transactions"
    IDENTITY = "identity"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class PluggyItem:
    """A Pluggy item (one linked bank connection)."""

    id: UUID
    status: str
    error: str | None
    updated_at: datetime
    connector_name: str | None = None


@dataclass(frozen=True, slots=True)
class BankAccount:
    """A bank account collected from a Pluggy item."""

    id: UUID
    item_id: UUID
    type: str
    name: str
    balance_cents: int
    currency: str
    institution: str | None = None


@dataclass(frozen=True, slots=True)
class BankTransaction:
    """A posted movement on a bank account."""

    id: UUID
    account_id: UUID
    item_id: UUID
    day: date
    description: str
    amount_cents: int
    currency: str
    category: str | None
    direction: str = "DEBIT"
    description_raw: str | None = None


@dataclass(frozen=True, slots=True)
class BankExpense:
    """A real spend collected from the bank, ready for the summary.

    ``amount_cents`` is always positive: the sign carried by the raw bank
    movement is discarded once the direction has been used to tell a spend
    from an inflow.
    """

    id: UUID
    day: date
    description: str
    amount_cents: int
    category: Category
    institution: str | None
    raw_category: str | None = None
    description_raw: str | None = None


@dataclass(frozen=True, slots=True)
class BankIdentity:
    """The account holder identity reported by the bank."""

    item_id: UUID
    full_name: str | None
    document: str | None
    document_type: str | None
    birth_date: str | None


def to_cents(value: object) -> int:
    """Convert a BRL amount to integer cents, rounding half up.

    Negative values are allowed because bank transactions carry their sign.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise InvalidAmount("amount must be a number.")

    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidAmount("amount must be a number.") from exc

    if not amount.is_finite():
        raise InvalidAmount("amount must be finite.")

    return int(amount.quantize(_CENT, rounding=ROUND_HALF_UP) * 100)
