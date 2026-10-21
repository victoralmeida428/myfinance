"""Unit tests for category classification adapters."""

import json
from collections.abc import Callable

import httpx
import pytest

from myfinance.application.errors import ProviderError
from myfinance.config import Settings
from myfinance.domain.categories import Category
from myfinance.infrastructure.categorization import (
    FallbackCategoryClassifier,
    JevCategoryClassifier,
    KeywordCategoryClassifier,
    classify_keywords,
)

_CATEGORY_KEYS = {
    "alimentacao",
    "transporte",
    "lazer",
    "saude",
    "servicos",
    "outros",
}


def test_classify_keywords_matches_accents_and_case() -> None:
    assert classify_keywords("ALMOÇO no mercado") is Category.ALIMENTACAO


def test_classify_keywords_matches_health_terms() -> None:
    assert classify_keywords("farmácia") is Category.SAUDE


def test_classify_keywords_abstains_on_unknown_text() -> None:
    assert classify_keywords("xyz") is None


class StubClassifier:
    def __init__(self, result: Category | None, *, raises: bool = False) -> None:
        self._result = result
        self._raises = raises

    async def classify(self, text: str) -> Category | None:
        if self._raises:
            raise ProviderError("provider down")
        return self._result


async def test_fallback_classifier_prefers_the_primary_result() -> None:
    classifier = FallbackCategoryClassifier(
        StubClassifier(Category.LAZER), StubClassifier(Category.SAUDE)
    )

    assert await classifier.classify("cinema") is Category.LAZER


async def test_fallback_classifier_uses_the_fallback_on_abstention() -> None:
    classifier = FallbackCategoryClassifier(
        StubClassifier(None), StubClassifier(Category.SAUDE)
    )

    assert await classifier.classify("cinema") is Category.SAUDE


async def test_fallback_classifier_uses_the_fallback_on_provider_error() -> None:
    classifier = FallbackCategoryClassifier(
        StubClassifier(None, raises=True), StubClassifier(Category.SAUDE)
    )

    assert await classifier.classify("cinema") is Category.SAUDE


async def test_keyword_classifier_uses_the_keyword_map() -> None:
    assert (
        await KeywordCategoryClassifier().classify("mercado")
        is Category.ALIMENTACAO
    )


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(*, token: str | None = "test-token") -> Settings:
    return Settings(_env_file=None, categorizer_api_token=token)


def _answer(
    *,
    choice: str | None = None,
    probabilities: dict[str, float] | None = None,
) -> dict[str, object]:
    answer: dict[str, object] = {"type": "choice", "confidence": 1.0}
    if choice is not None:
        answer["choice"] = choice
    if probabilities is not None:
        answer["probabilities"] = probabilities
    return answer


def _response(answer: dict[str, object] | None) -> dict[str, object]:
    answers: dict[str, object] = {}
    if answer is not None:
        answers["category"] = answer
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def test_jev_without_a_token_abstains_without_a_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response(_answer(choice="lazer")))

    classifier = JevCategoryClassifier(
        _settings(token=None), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is None
    assert calls == []


async def test_jev_sends_the_expected_systemone_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_response(_answer(choice="lazer")))

    classifier = JevCategoryClassifier(_settings(), http_client=_client(handler))

    result = await classifier.classify("cinema")

    assert result is Category.LAZER
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    headers = captured["headers"]
    assert headers["authorization"] == "Bearer test-token"
    body = captured["body"]
    assert body["model"] == "jev-latest"
    assert body["state"] == "cinema"
    question = body["questions"]["category"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == _CATEGORY_KEYS


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("lazer", Category.LAZER),
        ("saude", Category.SAUDE),
    ],
)
async def test_jev_maps_the_choice_answer(
    choice: str, expected: Category
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(_answer(choice=choice)))

    classifier = JevCategoryClassifier(
        _settings(), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is expected


async def test_jev_falls_back_to_the_most_likely_category() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                _answer(
                    choice="banana",
                    probabilities={
                        "alimentacao": 0.1,
                        "transporte": 0.0,
                        "lazer": 0.7,
                        "saude": 0.1,
                        "servicos": 0.1,
                        "outros": 0.0,
                    },
                )
            ),
        )

    classifier = JevCategoryClassifier(
        _settings(), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is Category.LAZER


async def test_jev_abstains_when_the_answer_is_missing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(None))

    classifier = JevCategoryClassifier(
        _settings(), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is None


async def test_jev_disables_itself_after_an_auth_error() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": "unauthorized"})

    classifier = JevCategoryClassifier(
        _settings(), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is None
    assert await classifier.classify("cinema") is None
    assert len(calls) == 1


async def test_jev_stays_enabled_after_a_server_error() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_response(_answer(choice="lazer")))

    classifier = JevCategoryClassifier(
        _settings(), http_client=_client(handler)
    )

    assert await classifier.classify("cinema") is None
    assert await classifier.classify("cinema") is Category.LAZER
    assert len(calls) == 2
