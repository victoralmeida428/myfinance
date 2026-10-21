"""Language-model parser for messages the deterministic rules cannot handle."""

from __future__ import annotations

import json
from datetime import date

from myfinance.application.dto import ParsedMessage
from myfinance.application.ports import CategoryClassifier, LanguageModel
from myfinance.domain.categories import Category
from myfinance.domain.entries import EntryKind
from myfinance.domain.exceptions import InvalidAmount
from myfinance.domain.models import ChatMessage
from myfinance.domain.money import Money


def _system_prompt(today: date) -> str:
    return (
        "Você extrai lançamentos financeiros de mensagens em português do "
        "Brasil.\n"
        "Responda APENAS com um objeto JSON válido, sem markdown e sem texto "
        "adicional, exatamente neste formato:\n"
        '{"kind":"forecast|expense","amount_cents":123,'
        '"date":"YYYY-MM-DD",'
        '"category":"alimentacao|transporte|lazer|saude|servicos|outros",'
        '"description":"texto curto"}\n'
        "Regras:\n"
        "- amount_cents deve ser um número inteiro de centavos, nunca um "
        "decimal (R$ 80,50 => 8050).\n"
        "- kind: use 'forecast' para planos, previsões e orçamentos; use "
        "'expense' para gastos já realizados.\n"
        "- date: use a data informada pelo usuário; se não houver, use a data "
        f"de hoje ({today.isoformat()}).\n"
        "- category: use 'outros' quando nenhuma categoria for mencionada.\n"
        "- Categorias válidas: alimentacao, transporte, lazer, saude, "
        "servicos, outros."
    )


class OpenCodeMessageParser:
    """Asks a language model for strict JSON and validates the result."""

    def __init__(
        self,
        model: LanguageModel,
        classifier: CategoryClassifier | None = None,
    ) -> None:
        self._model = model
        self._classifier = classifier

    async def parse(self, text: str, *, today: date) -> ParsedMessage | None:
        messages = [
            ChatMessage(role="system", content=_system_prompt(today)),
            ChatMessage(role="user", content=text),
        ]
        raw = await self._model.complete(messages)

        try:
            payload = self._extract_object(raw)
            kind = EntryKind(payload["kind"])
            amount = Money(payload["amount_cents"])
            day = date.fromisoformat(payload["date"])
            description = payload["description"]
            if not isinstance(description, str):
                raise TypeError("description must be a string")
        except (
            json.JSONDecodeError,
            ValueError,
            KeyError,
            TypeError,
            InvalidAmount,
        ):
            return None

        json_category = _json_category(payload.get("category"))
        category = (
            await self._classifier.classify(text)
            if self._classifier is not None
            else None
        )
        if category is None:
            category = json_category
        if category is None:
            return None

        return ParsedMessage(
            kind=kind,
            amount=amount,
            day=day,
            category=category,
            description=description.strip() or category.label,
        )

    @staticmethod
    def _extract_object(raw: str) -> dict[str, object]:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end < start:
            raise ValueError("model output has no JSON object")
        payload = json.loads(raw[start : end + 1])
        if not isinstance(payload, dict):
            raise TypeError("model output is not a JSON object")
        return payload


def _json_category(raw_category: object) -> Category | None:
    """Resolve the JSON category leniently, tolerating a missing value."""
    if not isinstance(raw_category, str):
        return None
    try:
        return Category(raw_category)
    except ValueError:
        return None
