"""Metrics and security middleware tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from evaluation.metrics import evaluate

# ── Calibration metrics ──────────────────────────────────────────────


def test_evaluate_perfect_predictions():
    records = [
        {"predicted": "A", "probability": 1.0, "answer": "A"},
        {"predicted": "B", "probability": 0.9, "answer": "B"},
    ]
    report = evaluate(records)
    assert report.accuracy == 1.0
    assert report.brier == pytest.approx(0.005, abs=1e-3)


def test_evaluate_wrong_predictions():
    records = [
        {"predicted": "A", "probability": 0.9, "answer": "B"},
        {"predicted": "A", "probability": 0.8, "answer": "B"},
    ]
    report = evaluate(records)
    assert report.accuracy == 0.0
    assert report.brier == pytest.approx(0.5 * 0.81 + 0.5 * 0.64)
    assert report.log_loss > 1.0  # confident and wrong is heavily penalized


def test_evaluate_empty_records():
    report = evaluate([])
    assert report.questions == 0
    assert report.ece == 0.0


def test_bucket_assignment():
    records = [
        {"predicted": "A", "probability": 0.10, "answer": "A"},  # 0–20
        {"predicted": "A", "probability": 0.30, "answer": "A"},  # 20–40
        {"predicted": "A", "probability": 0.55, "answer": "B"},  # 40–60
        {"predicted": "A", "probability": 0.70, "answer": "A"},  # 60–80
        {"predicted": "A", "probability": 0.99, "answer": "A"},  # 80–100
    ]
    report = evaluate(records)
    assert report.buckets["0–20%"].count == 1
    assert report.buckets["20–40%"].count == 1
    assert report.buckets["40–60%"].count == 1
    assert report.buckets["60–80%"].count == 1
    assert report.buckets["80–100%"].count == 1


# ── Security middleware ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """Middleware reads cached settings; env changes need a cache reset."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client_with_env(**env: str) -> TestClient:
    from app.main import create_app
    from app.services.analysis.service import AnalysisService
    from app.services.jev.client import JevDecisionProvider
    from app.services.llm.null_provider import NullLLMProvider
    from tests.conftest import make_settings

    settings = make_settings(**env)

    class _StubJev(JevDecisionProvider):
        def __init__(self) -> None:
            super().__init__(settings=settings)

    app = create_app()
    app.state.analysis_service = AnalysisService(_StubJev(), NullLLMProvider())
    return TestClient(app)


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    client = _client_with_env()
    for _ in range(3):
        assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 429


def test_api_key_required_when_configured(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    client = _client_with_env(api_key="secret-key")

    # /health is open for monitoring.
    assert client.get("/health").status_code == 200
    # API routes require the header.
    assert client.get("/api/v1/providers").status_code == 401
    response = client.get("/api/v1/providers", headers={"X-API-Key": "secret-key"})
    assert response.status_code == 200


def test_api_key_disabled_by_default():
    client = _client_with_env(api_key="")
    assert client.get("/api/v1/providers").status_code == 200


def test_body_size_limit_rejects_large_bodies(monkeypatch):
    monkeypatch.setenv("MAX_BODY_BYTES", "64")
    client = _client_with_env()
    response = client.post(
        "/api/v1/analyze",
        json={"question": "x" * 500, "options": [{"id": "A", "text": "y"}, {"id": "B", "text": "z"}]},
    )
    assert response.status_code == 413
