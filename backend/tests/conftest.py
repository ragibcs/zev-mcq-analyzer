"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.schemas.common import Option

QUESTION = "What is the time complexity of binary search?"
OPTIONS = [
    Option(id="A", text="O(n)"),
    Option(id="B", text="O(log n)"),
    Option(id="C", text="O(n^2)"),
    Option(id="D", text="O(1)"),
]


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        decision_provider="jev",
        jev_api_key="test-key",
        llm_provider="none",
        openrouter_api_key="test-or-key",
        openrouter_model="openai/gpt-4o-mini",
        vercel_ai_gateway_api_key="test-v_key",
        vercel_ai_gateway_model="openai/gpt-4o-mini",
        _env_file=None,  # never read the developer's real .env in tests
    )
    base.update(overrides)
    return Settings(**base)


def jev_response(
    probabilities: dict[str, float],
    choice: str,
    confidence: float,
    model: str = "jev-1.13.0",
) -> dict[str, Any]:
    return {
        "model": model,
        "answers": {
            "mcq_answer": {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": confidence,
            }
        },
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


def llm_response(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"total_tokens": 42},
    }


def mock_transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
