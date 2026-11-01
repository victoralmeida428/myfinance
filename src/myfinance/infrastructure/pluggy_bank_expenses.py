"""Pluggy adapter that turns posted bank movements into real expenses.

Bank expenses are fetched on demand from Pluggy and never persisted: the
summary use cases are the only consumers. A movement only counts as an expense
when it is a ``DEBIT`` (this excludes bank inflows and credit-card payments,
which Pluggy reports as ``CREDIT``) and it is not a bookkeeping movement.
Transfers to another account registered in Pluggy, same-holder transfers,
internal reservations, credit-card payments and investments are not spending;
cash withdrawals are.

Same-holder transfers are recognised from Pluggy's ``Same person transfer``
category, from the account holder's name or document in the description, or by
pairing the debit with a credit of the same amount in another account owned by
the same holder.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from myfinance.application.errors import ProviderError
from myfinance.application.ports import (
    BankingProvider,
    CategoryClassifier,
    PluggyItemRepository,
)
from myfinance.domain.banking import (
    BankExpense,
    BankIdentity,
    BankTransaction,
    PluggyItem,
)
from myfinance.domain.categories import Category, coerce_category

__all__ = ["PluggyBankExpenseProvider"]

_LOGGER = logging.getLogger(__name__)

_ALWAYS_EXCLUDED_CATEGORIES = frozenset(
    {
        "credit card payment",
        "investments",
        "transfer - internal",
    }
)

_CASH_CATEGORIES = frozenset(
    {
        "same person transfer - cash",
        "transfer - cash",
    }
)

_CASH_DESCRIPTION_MARKERS = ("saque", "cash withdrawal")

_TRANSFER_DESCRIPTION_PREFIXES = (
    "pix enviado",
    "pix recebido",
    "transferencia enviada",
    "transferencia recebida",
    "ted enviado",
    "ted recebido",
)

_NAME_CONNECTIVES = frozenset({"de", "da", "do", "das", "dos", "e"})

_PAIRING_WINDOW_DAYS = 3

_CATEGORY_BY_RAW: dict[str, Category] = {
    "eating out": Category.ALIMENTACAO,
    "groceries": Category.ALIMENTACAO,
    "food delivery": Category.ALIMENTACAO,
    "taxi and ride-hailing": Category.TRANSPORTE,
    "gas stations": Category.TRANSPORTE,
    "public transportation": Category.TRANSPORTE,
    "parking": Category.TRANSPORTE,
    "leisure": Category.LAZER,
    "gaming": Category.LAZER,
    "sports goods": Category.LAZER,
    "bookstore": Category.LAZER,
    "pharmacy": Category.SAUDE,
    "health": Category.SAUDE,
    "services": Category.SERVICOS,
    "digital services": Category.SERVICOS,
    "telecommunications": Category.SERVICOS,
    "electricity": Category.SERVICOS,
    "internet": Category.SERVICOS,
    "housing": Category.SERVICOS,
    "bank fees": Category.SERVICOS,
    "shopping": Category.OUTROS,
    "online shopping": Category.OUTROS,
    "clothing": Category.OUTROS,
    "electronics": Category.OUTROS,
    "houseware": Category.OUTROS,
    "university": Category.OUTROS,
    "tax on financial operations": Category.OUTROS,
}


def _normalize(text: str | None) -> str:
    """Lowercase, remove accents and collapse whitespace in a raw category."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def _is_same_person_category(category: str) -> bool:
    """Return whether the category belongs to the same-person transfer tree."""
    return category == "same person transfer" or category.startswith(
        "same person transfer - "
    )


def _is_cash(category: str, description: str) -> bool:
    """Return whether a movement is a cash withdrawal, which is spending."""
    if category in _CASH_CATEGORIES:
        return True
    if category.startswith("same person transfer - cash"):
        return True
    return any(marker in description for marker in _CASH_DESCRIPTION_MARKERS)


def _is_transfer_category(category: str) -> bool:
    """Return whether the category belongs to a Pluggy transfer subtree."""
    return (
        category == "transfers"
        or category.startswith("transfer - ")
        or category.startswith("same person transfer")
        or category.startswith("third party transfer")
    )


def _looks_like_transfer(category: str, description: str) -> bool:
    return _is_transfer_category(category) or description.startswith(
        _TRANSFER_DESCRIPTION_PREFIXES
    )


def _name_tokens(name: str | None) -> frozenset[str]:
    """Return the distinctive tokens of a holder name."""
    if not name:
        return frozenset()
    return frozenset(
        token
        for token in _normalize(name).split()
        if len(token) >= 3 and token not in _NAME_CONNECTIVES
    )


def _mentions_holder(
    description: str, identity: BankIdentity | None
) -> bool:
    """Return whether a description names the holder by name or document."""
    if identity is None:
        return False
    if identity.document:
        document = re.sub(r"\D", "", identity.document)
        if document and document in re.sub(r"\D", "", description):
            return True
    holder_tokens = _name_tokens(identity.full_name)
    if not holder_tokens:
        return False
    matches = holder_tokens & set(_normalize(description).split())
    required = min(2, len(holder_tokens))
    return len(matches) >= required


def _holder_key(identity: BankIdentity | None, item_id: UUID) -> str:
    """Return a grouping key that pairs accounts only for the same holder."""
    if identity is not None:
        if identity.document:
            document = re.sub(r"\D", "", identity.document)
            if document:
                return f"document:{document}"
        if identity.full_name:
            return f"name:{_normalize(identity.full_name)}"
    return f"item:{item_id}"


@dataclass(frozen=True, slots=True)
class _Movement:
    """A bank transaction together with the holder data needed to pair it."""

    account_id: UUID
    account_type: str
    institution: str | None
    holder_key: str
    identity: BankIdentity | None
    transaction: BankTransaction


class PluggyBankExpenseProvider:
    """Collects real spends from the connected banks through Pluggy."""

    def __init__(
        self,
        banking: BankingProvider,
        items: PluggyItemRepository,
        classifier: CategoryClassifier,
    ) -> None:
        self._banking = banking
        self._items = items
        self._classifier = classifier
        self._identity_cache: dict[UUID, BankIdentity] = {}

    async def expenses(
        self, start: date, end: date
    ) -> Sequence[BankExpense]:
        items = await self._items.list_active()
        if not items:
            return ()

        identities = await self._identities(items)
        movements = await self._movements(items, identities, start, end)
        credits = self._credits(movements)

        expenses: list[BankExpense] = []
        for movement in movements:
            transaction = movement.transaction
            if transaction.direction != "DEBIT":
                continue
            if not start <= transaction.day <= end:
                continue

            raw_category = _normalize(transaction.category)
            description = _normalize(
                f"{transaction.description} "
                f"{transaction.description_raw or ''}"
            )
            if raw_category in _ALWAYS_EXCLUDED_CATEGORIES:
                continue
            if _is_cash(raw_category, description):
                pass
            elif _is_same_person_category(raw_category):
                continue
            elif _looks_like_transfer(raw_category, description):
                if _mentions_holder(description, movement.identity):
                    continue
                if self._has_internal_credit(movement, credits):
                    continue

            category = await self._category(
                raw_category, transaction.description
            )
            expenses.append(
                BankExpense(
                    id=transaction.id,
                    day=transaction.day,
                    description=transaction.description,
                    amount_cents=abs(transaction.amount_cents),
                    category=coerce_category(category),
                    institution=movement.institution,
                    raw_category=transaction.category,
                    description_raw=transaction.description_raw,
                )
            )
        return tuple(expenses)

    async def _identities(
        self, items: Sequence[PluggyItem]
    ) -> dict[UUID, BankIdentity | None]:
        """Load the holder identity of each item, tolerating lookup failures."""
        identities: dict[UUID, BankIdentity | None] = {}
        for item in items:
            cached = self._identity_cache.get(item.id)
            if cached is not None:
                identities[item.id] = cached
                continue
            try:
                identity = await self._banking.find_identity(item.id)
            except ProviderError as exc:
                _LOGGER.warning(
                    "Identity lookup failed for item %s: %s",
                    item.id,
                    type(exc).__name__,
                )
                identity = None
            if identity is not None:
                self._identity_cache[item.id] = identity
            identities[item.id] = identity
        return identities

    async def _movements(
        self,
        items: Sequence[PluggyItem],
        identities: dict[UUID, BankIdentity | None],
        start: date,
        end: date,
    ) -> list[_Movement]:
        """Fetch every movement, widening the window to catch pairing credits."""
        buffer = timedelta(days=_PAIRING_WINDOW_DAYS)
        movements: list[_Movement] = []
        for item in items:
            identity = identities.get(item.id)
            holder_key = _holder_key(identity, item.id)
            accounts = await self._banking.list_accounts(item.id)
            for account in accounts:
                transactions = await self._banking.list_transactions(
                    account.id, start=start - buffer, end=end + buffer
                )
                movements.extend(
                    _Movement(
                        account_id=account.id,
                        account_type=account.type,
                        institution=item.connector_name,
                        holder_key=holder_key,
                        identity=identity,
                        transaction=transaction,
                    )
                    for transaction in transactions
                )
        return movements

    @staticmethod
    def _credits(
        movements: Sequence[_Movement],
    ) -> dict[tuple[str, int], list[_Movement]]:
        """Index credits by holder and absolute amount."""
        credits: dict[tuple[str, int], list[_Movement]] = defaultdict(list)
        for movement in movements:
            if movement.transaction.direction == "CREDIT":
                credits[
                    (
                        movement.holder_key,
                        abs(movement.transaction.amount_cents),
                    )
                ].append(movement)
        return credits

    @staticmethod
    def _has_internal_credit(
        debit: _Movement,
        credits: dict[tuple[str, int], list[_Movement]],
    ) -> bool:
        """Return whether another registered account received the same amount."""
        key = (debit.holder_key, abs(debit.transaction.amount_cents))
        for credit in credits.get(key, ()):
            if credit.account_id == debit.account_id:
                continue
            difference = abs(
                (credit.transaction.day - debit.transaction.day).days
            )
            if difference > _PAIRING_WINDOW_DAYS:
                continue
            credit_category = _normalize(credit.transaction.category)
            if _is_same_person_category(credit_category):
                return True
            credit_description = _normalize(
                f"{credit.transaction.description} "
                f"{credit.transaction.description_raw or ''}"
            )
            if _mentions_holder(credit_description, credit.identity):
                return True
            if (
                credit.account_type == "CREDIT"
                and credit_category == "credit card payment"
            ):
                return True
        return False

    async def _category(
        self, raw_category: str, description: str
    ) -> Category:
        mapped = _CATEGORY_BY_RAW.get(raw_category)
        if mapped is not None:
            return mapped
        classified = await self._classifier.classify(description)
        return coerce_category(classified)
