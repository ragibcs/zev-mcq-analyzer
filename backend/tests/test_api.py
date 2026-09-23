"""API integration tests: /health, /analyze, /explain, /providers, /config."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import OPTIONS, QUESTION, jev_response, make_settings

ANALYZE_BODY = {
    "question": QUESTION,
    "options": [{"id": o.id, "text": o.text} for o in OPTIONS],
}

EXPLAIN_BODY = {
    **ANALYZE_BODY,
    "jev_result": {
        "predicted_option": "B",
        "confidence": 0.96,
        "distribution": [
            {"option_id": "A", "option_text": "O(n)", "probability": 0.02},
            {"option_id": "B", "option_text": "O(log n)", "probability": 0.96},
            {"option_id": "C", "option_text": "O(n^2)", "probability": 0.01},
            {"option_id": "D", "option_text": "O(1)", "probability": 0.01},
        ],
        "provider": "jev",
    },
}


def make_client(jev_handler, llm_handler=None, **settings_overrides) -> TestClient:
    """Build an app whose providers use mock transports."""
    import app.main as main_module

    settings = make_settings(**{"llm_provider": "none", **settings_overrides})

    from app.services.jev.client import JevDecisionProvider

    class _MockJev(JevDecisionProvider):
        def __init__(self) -> None:
            super().__init__(
                settings=settings,
                transport=httpx.MockTransport(jev_handler),
            )

    def decision_factory():
        return _MockJev()

    if llm_handler is not None:
        from app.services.llm.openrouter import OpenRouterProvider

        class _MockOR(OpenRouterProvider):
            def __init__(self) -> None:
                super().__init__(settings=settings)
                self._client = type(self._client)(
                    provider_name="OpenRouter",
                    api_key=settings.openrouter_api_key,
                    model=settings.openrouter_model,
                    base_url=settings.openrouter_base_url,
                    settings=settings,
                    transport=httpx.MockTransport(llm_handler),
                )

        def llm_factory():
            return _MockOR()

    else:
        def llm_factory():
            from app.services.llm.null_provider import NullLLMProvider

            return NullLLMProvider()

    app = create_app()
    app.state.analysis_service = main_module.AnalysisService(
        decision_factory(), llm_factory()
    )
    return TestClient(app)


def test_health():
    client = make_client(lambda req: httpx.Response(200, json={}))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_success():
    def jev_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=jev_response(
                {"opt_a": 0.02, "opt_b": 0.96, "opt_c": 0.01, "opt_d": 0.01},
                "opt_b",
                0.95,
            ),
        )

    client = make_client(jev_handler)
    response = client.post("/api/v1/analyze", json=ANALYZE_BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["predicted_option"] == "B"
    assert data["provider"] == "jev"
    assert data["confidence"] == pytest.approx(0.95)
    assert len(data["distribution"]) == 4
    assert data["distribution"][1] == {
        "option_id": "B",
        "option_text": "O(log n)",
        "probability": 0.96,
    }


def test_analyze_invalid_request():
    client = make_client(lambda req: httpx.Response(200, json={}))
    response = client.post("/api/v1/analyze", json={"question": "", "options": []})
    assert response.status_code == 422


def test_analyze_single_option_rejected():
    client = make_client(lambda req: httpx.Response(200, json={}))
    response = client.post(
        "/api/v1/analyze",
        json={"question": "Q?", "options": [{"id": "A", "text": "x"}]},
    )
    assert response.status_code == 422


def test_analyze_jev_unavailable_maps_to_5xx():
    def jev_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(529)

    client = make_client(jev_handler)
    response = client.post("/api/v1/analyze", json=ANALYZE_BODY)
    assert response.status_code == 503  # transient overload
    assert "No prediction" in response.json()["detail"] or "unavailable" in response.json()["detail"]


def test_analyze_jev_auth_failure_maps_to_502():
    def jev_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = make_client(jev_handler)
    response = client.post("/api/v1/analyze", json=ANALYZE_BODY)
    assert response.status_code == 502


def test_explain_with_openrouter_provider():
    def jev_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jev_response({}, "opt_b", 0.96))

    def llm_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Why B?\nHalving the search space yields log time.\n"
                            "Why not A? Linear search is slower.\n"
                            "Why not C? No quadratic work occurs.\n"
                            "Why not D? Constant time is impossible here.\n"
                            "96% is Jev's estimate, not a guarantee."
                        }
                    }
                ]
            },
        )

    client = make_client(
        jev_handler, llm_handler, llm_provider="openrouter"
    )
    response = client.post("/api/v1/explain", json=EXPLAIN_BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openrouter"
    assert data["restated_prediction"] == "B"
    assert data["restated_confidence_pct"] == "96%"
    assert "Halving" in data["summary"]


def test_explain_when_llm_none_returns_503():
    client = make_client(lambda req: httpx.Response(200, json={}), llm_provider="none")
    response = client.post("/api/v1/explain", json=EXPLAIN_BODY)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_explain_provider_failure_names_provider():
    def llm_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = make_client(
        lambda req: httpx.Response(200, json={}),
        llm_handler,
        llm_provider="openrouter",
    )
    response = client.post("/api/v1/explain", json=EXPLAIN_BODY)
    assert response.status_code == 502
    assert "OpenRouter" in response.json()["detail"]


def test_providers_endpoint_reports_without_secrets():
    client = make_client(
        lambda req: httpx.Response(200, json={}),
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        llm_provider="openrouter",
    )
    response = client.get("/api/v1/providers")
    assert response.status_code == 200
    data = response.json()
    assert data["decision_provider"] == "jev"
    assert data["llm_provider"] == "openrouter"
    assert data["llm_available"] is True
    raw = response.text
    assert "test-key" not in raw
    assert "test-or-key" not in raw


def test_config_endpoint_no_secrets():
    client = make_client(lambda req: httpx.Response(200, json={}))
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert "test-key" not in response.text
