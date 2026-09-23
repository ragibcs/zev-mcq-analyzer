"""LLM provider tests (spec §33): OpenRouter, Vercel Gateway, factory."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ConfigurationError, LLMProviderError
from app.services.llm.factory import get_llm_provider
from app.services.llm.openrouter import OpenRouterProvider
from app.services.llm.vercel_gateway import VercelGatewayProvider
from tests.conftest import QUESTION, llm_response, make_settings

JEV_RESULT = {
    "predicted_option": "B",
    "confidence": 0.96,
    "distribution": [
        {"option_id": "A", "option_text": "O(n)", "probability": 0.02},
        {"option_id": "B", "option_text": "O(log n)", "probability": 0.96},
        {"option_id": "C", "option_text": "O(n^2)", "probability": 0.01},
        {"option_id": "D", "option_text": "O(1)", "probability": 0.01},
    ],
    "provider": "jev",
}

EXPLANATION_TEXT = (
    "Why B?\n"
    "Binary search repeatedly halves the search space, giving O(log n).\n"
    "Why not A? Linear scan checks every element.\n"
    "Why not C? Quadratic growth never occurs in binary search.\n"
    "Why not D? Constant time cannot cover an arbitrary search space.\n"
    "96% is Jev's estimated confidence, not a guarantee."
)


def _openrouter(handler, **overrides):
    return OpenRouterProvider(
        settings=make_settings(**overrides),
        transport=httpx.MockTransport(handler),
    )


def _vercel(handler, **overrides):
    return VercelGatewayProvider(
        settings=make_settings(**overrides),
        transport=httpx.MockTransport(handler),
    )


# ── OpenRouter ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openrouter_explanation():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=llm_response(EXPLANATION_TEXT))

    provider = _openrouter(handler)
    result = await provider.explain(
        QUESTION,
        [("A", "O(n)"), ("B", "O(log n)"), ("C", "O(n^2)"), ("D", "O(1)")],
        JEV_RESULT,
    )

    assert captured["url"].startswith("https://openrouter.ai/api/v1/chat/completions")
    assert captured["auth"] == "Bearer test-or-key"
    assert captured["body"]["model"] == "openai/gpt-4o-mini"

    assert result.provider == "openrouter"
    assert "Binary search repeatedly halves" in result.summary
    # The Jev prediction is restated, not re-derived from LLM output.
    assert result.restated_prediction == "B"
    assert result.restated_confidence_pct == "96%"
    assert set(result.per_option) == {"A", "C", "D"}


@pytest.mark.asyncio
async def test_openrouter_failure_maps_to_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream down"})

    provider = _openrouter(handler)
    with pytest.raises(LLMProviderError, match="OpenRouter"):
        await provider.explain(QUESTION, [("A", "x"), ("B", "y")], JEV_RESULT)


@pytest.mark.asyncio
async def test_openrouter_invalid_response_structure():
    def handler(request: httpx.Request) -> httpx.Response:
        # Missing choices[0].message.content entirely.
        return httpx.Response(200, json={"unexpected": True})

    provider = _openrouter(handler)
    with pytest.raises(LLMProviderError, match="unexpected response structure"):
        await provider.explain(QUESTION, [("A", "x"), ("B", "y")], JEV_RESULT)


@pytest.mark.asyncio
async def test_openrouter_empty_content_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=llm_response("   "))

    provider = _openrouter(handler)
    with pytest.raises(LLMProviderError, match="empty"):
        await provider.explain(QUESTION, [("A", "x"), ("B", "y")], JEV_RESULT)


def test_openrouter_requires_key_and_model():
    with pytest.raises(ConfigurationError):
        OpenRouterProvider(settings=make_settings(openrouter_api_key=""))
    with pytest.raises(ConfigurationError):
        OpenRouterProvider(settings=make_settings(openrouter_model=""))


# ── Vercel AI Gateway ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vercel_explanation():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=llm_response(EXPLANATION_TEXT))

    provider = _vercel(handler)
    result = await provider.explain(
        QUESTION,
        [("A", "O(n)"), ("B", "O(log n)"), ("C", "O(n^2)"), ("D", "O(1)")],
        JEV_RESULT,
    )

    assert captured["url"].startswith("https://ai-gateway.vercel.sh/v1/chat/completions")
    assert captured["auth"] == "Bearer test-v_key"
    assert result.provider == "vercel"
    assert result.restated_prediction == "B"


@pytest.mark.asyncio
async def test_vercel_failure_names_the_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "gateway down"})

    provider = _vercel(handler)
    with pytest.raises(LLMProviderError, match="Vercel AI Gateway"):
        await provider.explain(QUESTION, [("A", "x"), ("B", "y")], JEV_RESULT)


@pytest.mark.asyncio
async def test_vercel_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    provider = _vercel(handler)
    with pytest.raises(LLMProviderError, match="unexpected response structure"):
        await provider.explain(QUESTION, [("A", "x"), ("B", "y")], JEV_RESULT)


def test_vercel_requires_key_and_model():
    with pytest.raises(ConfigurationError):
        VercelGatewayProvider(settings=make_settings(vercel_ai_gateway_api_key=""))
    with pytest.raises(ConfigurationError):
        VercelGatewayProvider(settings=make_settings(vercel_ai_gateway_model=""))


# ── Factory (spec §23 / §33) ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """Factory tests set env vars; the lru_cache must not leak between them."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_factory_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODEL", "m")
    provider = get_llm_provider()
    assert isinstance(provider, OpenRouterProvider)


def test_factory_vercel(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vercel")
    monkeypatch.setenv("VERCEL_AI_GATEWAY_API_KEY", "k")
    monkeypatch.setenv("VERCEL_AI_GATEWAY_MODEL", "m")
    provider = get_llm_provider()
    assert isinstance(provider, VercelGatewayProvider)


def test_factory_none(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    from app.services.llm.null_provider import NullLLMProvider

    assert isinstance(get_llm_provider(), NullLLMProvider)


def test_factory_invalid_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "banana")
    with pytest.raises(ConfigurationError):
        get_llm_provider()


# ── pick() for comparison mode ───────────────────────────────────────


@pytest.mark.asyncio
async def test_openrouter_pick_returns_letter():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=llm_response("B"))

    provider = _openrouter(handler)
    choice = await provider.pick(
        QUESTION, [("A", "O(n)"), ("B", "O(log n)"), ("C", "O(n^2)"), ("D", "O(1)")]
    )
    assert choice == "B"
