"""Pluggy adapter for bank accounts, transactions and identity.

The Pluggy SDK is blocking (urllib3), so every SDK call runs in a worker thread
through :func:`anyio.to_thread.run_sync`; the event loop never blocks. The
adapter maps SDK models to pure domain types and never lets SDK exceptions
escape as themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import anyio
import urllib3
from pluggy_sdk import (
    Account,
    AccountApi,
    ApiClient,
    ApiException,
    IdentityApi,
    IdentityResponse,
    Transaction,
    TransactionApi,
)

from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.banking import (
    BankAccount,
    BankIdentity,
    BankTransaction,
    to_cents,
)
from myfinance.infrastructure.pluggy_client import PluggyApiClientFactory

__all__ = ["PluggyBankingProvider"]

_MAX_TRANSACTION_PAGES = 20
_REQUEST_TIMEOUT_SECONDS = 30


def _next_after(next_value: str | None) -> str | None:
    """Extract the decoded ``after`` cursor from a ready-to-use ``next`` value."""
    if not next_value:
        return None
    query = urlparse(next_value).query
    values = parse_qs(query).get("after")
    if values:
        return values[0]
    return None


class PluggyBankingProvider:
    """Fetches banking data from Pluggy on behalf of the application."""

    def __init__(self, settings: Settings) -> None:
        self._factory = PluggyApiClientFactory(settings)

    async def list_accounts(self, item_id: UUID) -> Sequence[BankAccount]:
        client = await self._factory.client()
        try:
            accounts = await anyio.to_thread.run_sync(
                self._fetch_accounts, client, item_id, abandon_on_cancel=True
            )
        except (ApiException, urllib3.exceptions.HTTPError) as exc:
            raise ProviderError(
                "Pluggy rejected the accounts request."
            ) from exc
        return tuple(self._map_account(account) for account in accounts)

    async def list_transactions(
        self, account_id: UUID, *, start: date, end: date
    ) -> Sequence[BankTransaction]:
        client = await self._factory.client()
        try:
            item_id, transactions = await anyio.to_thread.run_sync(
                self._fetch_transactions,
                client,
                account_id,
                start,
                end,
                abandon_on_cancel=True,
            )
        except (ApiException, urllib3.exceptions.HTTPError) as exc:
            raise ProviderError(
                "Pluggy rejected the transactions request."
            ) from exc
        return tuple(
            self._map_transaction(transaction, item_id)
            for transaction in transactions
        )

    async def find_identity(self, item_id: UUID) -> BankIdentity | None:
        client = await self._factory.client()
        try:
            identity = await anyio.to_thread.run_sync(
                self._fetch_identity, client, item_id, abandon_on_cancel=True
            )
        except (ApiException, urllib3.exceptions.HTTPError) as exc:
            raise ProviderError(
                "Pluggy rejected the identity request."
            ) from exc
        if identity is None:
            return None
        return self._map_identity(identity)

    @staticmethod
    def _fetch_accounts(client: ApiClient, item_id: UUID) -> Sequence[Account]:
        """Blocking call: list the accounts of one item."""
        return AccountApi(client).accounts_list(
            item_id=item_id, _request_timeout=_REQUEST_TIMEOUT_SECONDS
        ).results

    @staticmethod
    def _fetch_transactions(
        client: ApiClient, account_id: UUID, start: date, end: date
    ) -> tuple[UUID, Sequence[Transaction]]:
        """Blocking call: resolve the item id and page through the movements."""
        account = AccountApi(client).accounts_retrieve(
            id=str(account_id), _request_timeout=_REQUEST_TIMEOUT_SECONDS
        )
        item_id = UUID(str(account.item_id))
        api = TransactionApi(client)
        results: list[Transaction] = []
        after: str | None = None
        for _ in range(_MAX_TRANSACTION_PAGES):
            page = api.transactions_list_by_cursor(
                account_id=account_id,
                date_from=datetime.combine(start, time.min),
                date_to=datetime.combine(end, time.max),
                after=after,
                _request_timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            results.extend(page.results)
            after = _next_after(page.next)
            if after is None:
                break
        return item_id, results

    @staticmethod
    def _fetch_identity(
        client: ApiClient, item_id: UUID
    ) -> IdentityResponse | None:
        """Blocking call: fetch the identity attached to one item."""
        return IdentityApi(client).identity_find_by_item(
            item_id=item_id, _request_timeout=_REQUEST_TIMEOUT_SECONDS
        )

    @staticmethod
    def _map_account(account: Account) -> BankAccount:
        return BankAccount(
            id=UUID(str(account.id)),
            item_id=UUID(str(account.item_id)),
            type=account.type,
            name=account.name or account.marketing_name or "Conta",
            balance_cents=to_cents(account.balance),
            currency=account.currency_code,
        )

    @staticmethod
    def _map_transaction(
        transaction: Transaction, item_id: UUID
    ) -> BankTransaction:
        return BankTransaction(
            id=UUID(str(transaction.id)),
            account_id=UUID(str(transaction.account_id)),
            item_id=item_id,
            day=transaction.var_date.date(),
            description=(
                transaction.description
                or transaction.description_raw
                or "Transação"
            ),
            amount_cents=to_cents(transaction.amount),
            currency=transaction.currency_code,
            category=transaction.category,
            direction=transaction.type,
        )

    @staticmethod
    def _map_identity(identity: IdentityResponse) -> BankIdentity:
        birth_date = identity.birth_date
        return BankIdentity(
            item_id=UUID(str(identity.item_id)),
            full_name=identity.full_name,
            document=identity.document,
            document_type=identity.document_type,
            birth_date=birth_date.isoformat() if birth_date is not None else None,
        )
