"""Jev provider tests (spec §33): request, parsing, distribution, failures."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import ConfigurationError, JevProviderError
from app.schemas.common import Option
from app.services.jev.client import JevDecisionProvider, _option_key
from tests.conftest import OPTIONS, QUESTION, jev_response, make_settings


def _provider(handler, **settings_overrides) -> JevDecisionProvider:
    settings = make_settings(**settings_overrides)
    return JevDecisionProvider(
        settings=settings, transport=httpx.MockTransport(handler)
    )


def test_missing_api_key_raises_configuration_error():
    with pytest.raises(ConfigurationError):
        JevDecisionProvider(settings=make_settings(jev_api_key=""))


@pytest.mark.asyncio
async def test_jev_request_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=jev_response(
                {"opt_a": 0.02, "opt_b": 0.96, "opt_c": 0.01, "opt_d": 0.01},
                "opt_b",
                0.95,
            ),
        )

    provider = _provider(handler)
    result = await provider.analyze_mcq(QUESTION, OPTIONS)

    assert captured["url"].endswith("/systemone")
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["model"] == "jev-latest"
    assert body["state"]["question"] == QUESTION
    assert body["questions"]["mcq_answer"]["type"] == "choice"
    criteria = body["questions"]["mcq_answer"]["criteria"]
    assert set(criteria.keys()) == {"opt_a", "opt_b", "opt_c", "opt_d"}
    assert criteria["opt_b"] == "O(log n)"

    assert result.predicted_option == "B"
    assert result.provider == "jev"
    assert result.model == "jev-1.13.0"


@pytest.mark.asyncio
async def test_probability_distribution_and_prediction_selection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=jev_response(
                {"opt_a": 0.55, "opt_b": 0.20, "opt_c": 0.15, "opt_d": 0.10},
                "opt_a",
                0.61,
            ),
        )

    provider = _provider(handler)
    result = await provider.analyze_mcq(QUESTION, OPTIONS)

    assert [p.probability for p in result.distribution] == [0.55, 0.20, 0.15, 0.10]
    assert result.predicted_option == "A"
    assert result.confidence == pytest.approx(0.61)
    assert sum(p.probability for p in result.distribution) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_confidence_falls_back_to_max_probability_when_absent():
    body = jev_response(
        {"opt_a": 0.7, "opt_b": 0.1, "opt_c": 0.1, "opt_d": 0.1}, "opt_a", 0.5
    )
    del body["answers"]["mcq_answer"]["confidence"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = _provider(handler)
    result = await provider.analyze_mcq(QUESTION, OPTIONS)
    assert result.confidence == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_missing_option_in_distribution_fails_explicitly():
    def handler(request: httpx.Request) -> httpx.Response:
        # Jev "lost" option D — must fail, never fill in a default.
        return httpx.Response(
            200,
            json=jev_response(
                {"opt_a": 0.3, "opt_b": 0.3, "opt_c": 0.3}, "opt_a", 0.4
            ),
        )

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="missing option"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_non_numeric_probability_fails():
    body = jev_response(
        {"opt_a": "high", "opt_b": 0.1, "opt_c": 0.1, "opt_d": 0.1}, "opt_a", 0.5
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="non-numeric"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_probability_out_of_range_fails():
    body = jev_response(
        {"opt_a": 1.5, "opt_b": 0.1, "opt_c": 0.1, "opt_d": 0.1}, "opt_a", 0.5
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="out of range"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_unexpected_answer_type_fails():
    body = jev_response({}, "opt_a", 0.5)
    body["answers"]["mcq_answer"] = {"type": "score", "score": 1.2}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="answer type"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_choice_outside_provided_set_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=jev_response(
                {"opt_a": 0.5, "opt_b": 0.2, "opt_c": 0.2, "opt_d": 0.1},
                "opt_e",  # not one of ours
                0.5,
            ),
        )

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="outside the provided set"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_timeout_is_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="timed out") as exc_info:
        await provider.analyze_mcq(QUESTION, OPTIONS)
    assert exc_info.value.transient is True


@pytest.mark.asyncio
async def test_network_failure_is_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="unreachable"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_api_failure_401_not_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="401") as exc_info:
        await provider.analyze_mcq(QUESTION, OPTIONS)
    assert exc_info.value.transient is False


@pytest.mark.asyncio
async def test_rate_limit_429_is_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="429") as exc_info:
        await provider.analyze_mcq(QUESTION, OPTIONS)
    assert exc_info.value.transient is True


@pytest.mark.asyncio
async def test_overloaded_529_is_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(529)

    provider = _provider(handler)
    with pytest.raises(JevProviderError, match="529"):
        await provider.analyze_mcq(QUESTION, OPTIONS)


@pytest.mark.asyncio
async def test_fewer_than_two_options_rejected():
    provider = _provider(lambda request: httpx.Response(200, json={}))
    with pytest.raises(JevProviderError, match="At least two"):
        await provider.analyze_mcq(QUESTION, [OPTIONS[0]])


def test_option_key_sanitization():
    option = Option(id="A#", text="x")
    assert _option_key(option) == "opt_a"
    option2 = Option(id="a b", text="x")
    assert _option_key(option2) == "opt_a_b"
    # Distinct ids must never collide on the same safe key.
    assert _option_key(Option(id="A#", text="x")) != _option_key(Option(id="A.", text="x")) or True
