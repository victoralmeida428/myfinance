"""Banking queries and Pluggy item registration."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import UUID

from myfinance.application.dto import (
    AccountsAnswer,
    BankingAnswer,
    IdentityAnswer,
    NoPluggyItem,
    TransactionsAnswer,
)
from myfinance.application.ports import (
    BankingProvider,
    BankingRepository,
    Clock,
    DateReferenceExtractor,
    DateResolver,
    IntentRouter,
    PluggyItemRepository,
)
from myfinance.application.use_cases.common import strip_accents
from myfinance.domain.banking import BankingIntent, PluggyItem

__all__ = ["HandleBankingQueryUseCase", "RegisterPluggyItemUseCase"]


class RegisterPluggyItemUseCase:
    """Record the latest state of the linked Pluggy item."""

    def __init__(self, items: PluggyItemRepository, clock: Clock) -> None:
        self._items = items
        self._clock = clock

    async def execute(
        self,
        item_id: UUID,
        *,
        status: str = "created",
        error: str | None = None,
        connector_name: str | None = None,
    ) -> PluggyItem:
        item = PluggyItem(
            id=item_id,
            status=status,
            error=error,
            updated_at=self._clock.now(),
            connector_name=connector_name,
        )
        await self._items.upsert(item)
        return item


class HandleBankingQueryUseCase:
    """Answer a banking question about the connected account, when possible."""

    def __init__(
        self,
        router: IntentRouter,
        items: PluggyItemRepository,
        provider: BankingProvider,
        banking: BankingRepository,
        clock: Clock,
        dates: DateResolver,
        references: DateReferenceExtractor,
    ) -> None:
        self._router = router
        self._items = items
        self._provider = provider
        self._banking = banking
        self._clock = clock
        self._dates = dates
        self._references = references

    async def execute(
        self,
        text: str,
        *,
        intent: BankingIntent | None = None,
    ) -> BankingAnswer | None:
        intent = intent if intent is not None else await self._router.route(text)
        if intent is BankingIntent.NONE:
            return None

        items = await self._items.list_active()
        if not items:
            return NoPluggyItem()

        if intent is BankingIntent.ACCOUNTS:
            accounts = []
            for item in items:
                item_accounts = await self._provider.list_accounts(item.id)
                accounts.extend(
                    replace(account, institution=item.connector_name)
                    for account in item_accounts
                )
            await self._banking.save_accounts(accounts)
            return AccountsAnswer(accounts=accounts)

        if intent is BankingIntent.TRANSACTIONS:
            start, end = self._window(text)
            transactions = []
            for item in items:
                item_accounts = await self._provider.list_accounts(item.id)
                for account in item_accounts:
                    if account.type != "BANK":
                        continue
                    transactions.extend(
                        await self._provider.list_transactions(
                            account.id, start=start, end=end
                        )
                    )
            await self._banking.save_transactions(transactions)
            return TransactionsAnswer(
                transactions=transactions, start=start, end=end
            )

        identity = None
        for item in items:
            found = await self._provider.find_identity(item.id)
            if found is not None:
                identity = found
                break
        if identity is not None:
            await self._banking.save_identity(identity)
        return IdentityAnswer(identity=identity)

    def _window(self, text: str) -> tuple[date, date]:
        today = self._clock.today()
        reference = self._references.extract(text)
        day = self._dates.resolve(reference, today=today) or today
        if "mes" in strip_accents(text):
            return today.replace(day=1), today
        return day, day
