"""Shared OpenAI-compatible chat-completions plumbing.

OpenRouter and Vercel AI Gateway both expose the OpenAI Chat Completions
schema, so the request/response logic lives here once and the two providers
only declare their endpoints and auth headers. No application logic is
duplicated between providers.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import LLMProviderError
from app.core.logging import get_logger
from app.services.llm.base import ExplanationResult

logger = get_logger(__name__)

EXPLAIN_SYSTEM = (
    "You explain MCQ analysis results. You are given a question, the answer "
    "options, and a probability distribution produced by a separate decision "
    "engine called Jev. Explain why the highest-probability option may be "
    "correct and why the alternatives may be wrong. NEVER invent or change "
    "the probabilities; treat them as fixed model estimates, not guarantees. "
    "Be concise and factual."
)

_EXPLAIN_USER_TMPL = """Question:
{question}

Options:
{options}

Jev estimate (fixed, do not modify):
Predicted option: {predicted}
Confidence: {confidence}
Distribution: {distribution}

Write an explanation for a student. Structure:
1. "Why {predicted}?" — one short paragraph.
2. One short line per alternative option, "Why not <id>? <reason>".
3. One line reminding the reader that {confidence_pct} is Jev's estimated confidence, not a guarantee of correctness."""

PICK_SYSTEM = (
    "You answer multiple-choice questions. Reply with ONLY the letter of the "
    "best option (e.g. B). No explanation, no extra text."
)


class OpenAICompatClient:
    """Minimal async client for OpenAI-compatible /chat/completions endpoints."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._settings = settings or get_settings()
        # Optional injection point for tests (httpx.MockTransport).
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, system: str, user: str, *, max_tokens: int = 700) -> str:
        if not self._api_key:
            raise LLMProviderError(
                f"{self._provider_name} API key is not configured.",
                provider=self._provider_name,
            )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        timeout = self._settings.request_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            logger.error(
                "LLM request timed out",
                extra={"data": {"provider": self._provider_name}},
            )
            raise LLMProviderError(
                f"{self._provider_name} request timed out.",
                provider=self._provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "LLM network error",
                extra={
                    "data": {
                        "provider": self._provider_name,
                        "error": type(exc).__name__,
                    }
                },
            )
            raise LLMProviderError(
                f"{self._provider_name} is unreachable.",
                provider=self._provider_name,
            ) from exc

        if response.status_code != 200:
            logger.error(
                "LLM HTTP error",
                extra={
                    "data": {
                        "provider": self._provider_name,
                        "status_code": response.status_code,
                    }
                },
            )
            raise LLMProviderError(
                f"{self._provider_name} request failed (HTTP {response.status_code}).",
                provider=self._provider_name,
                status_code=response.status_code,
            )

        try:
            body: dict[str, Any] = response.json()
            content: str | None = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.error(
                "LLM malformed response",
                extra={"data": {"provider": self._provider_name}},
            )
            raise LLMProviderError(
                f"{self._provider_name} returned an unexpected response structure.",
                provider=self._provider_name,
            ) from exc

        if not content or not content.strip():
            raise LLMProviderError(
                f"{self._provider_name} returned an empty response.",
                provider=self._provider_name,
            )
        return content.strip()


def render_explain_user_prompt(
    question: str,
    options: list[tuple[str, str]],
    jev_result: dict,
) -> str:
    options_block = "\n".join(f"{oid}. {text}" for oid, text in options)
    distribution = jev_result.get("distribution") or []
    dist_block = ", ".join(
        f"{d.get('option_id', '?')}={float(d.get('probability', 0.0)):.2f}"
        for d in distribution
        if isinstance(d, dict)
    )
    confidence = jev_result.get("confidence")
    confidence_pct = (
        f"{float(confidence) * 100:.0f}%"
        if isinstance(confidence, (int, float))
        else "N/A"
    )
    return _EXPLAIN_USER_TMPL.format(
        question=question[:4000],
        options=options_block,
        predicted=jev_result.get("predicted_option", "?"),
        confidence=confidence,
        distribution=dist_block or "unavailable",
        confidence_pct=confidence_pct,
    )


def render_pick_user_prompt(question: str, options: list[tuple[str, str]]) -> str:
    options_block = "\n".join(f"{oid}. {text}" for oid, text in options)
    return f"Question:\n{question[:4000]}\n\nOptions:\n{options_block}"


def extract_choice(text: str, valid_ids: list[str]) -> str | None:
    """Pull the first valid option id from LLM output (pick mode)."""
    import re

    for match in re.finditer(r"\b([A-Za-z])\b", text[:200]):
        candidate = match.group(1).upper()
        if candidate in valid_ids:
            return candidate
    return None


def build_explanation(
    *,
    provider_name: str,
    model: str,
    text: str,
    question: str,
    options: list[tuple[str, str]],
    jev_result: dict,
) -> ExplanationResult:
    """Split the raw LLM completion into a normalized ExplanationResult.

    The Jev prediction/confidence are restated from ``jev_result`` — the LLM
    cannot alter them, so no untrusted LLM output is parsed as probability.
    """
    predicted = str(jev_result.get("predicted_option", ""))
    distribution = jev_result.get("distribution") or []
    confidence = jev_result.get("confidence")
    confidence_pct = (
        f"{float(confidence) * 100:.0f}%"
        if isinstance(confidence, (int, float))
        else "N/A"
    )

    # Try to split the "Why not X?" lines into per-option entries; fall back
    # to a single summary block when the model's formatting drifts.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    per_option: dict[str, str] = {}
    for line in lines:
        for option_id, _ in options:
            lowered = line.lower()
            if option_id and (
                lowered.startswith(f"why not {option_id.lower()}")
                or lowered.startswith(f"- why not {option_id.lower()}")
                or lowered.startswith(f"{option_id.lower()}:")
            ):
                per_option[option_id] = line.lstrip("- ").strip()
                break

    return ExplanationResult(
        summary=text,
        per_option=per_option,
        provider=provider_name,
        model=model,
        restated_prediction=predicted,
        restated_confidence_pct=confidence_pct,
        meta={
            "question_preview": question[:200],
            "distribution_len": len(distribution),
        },
    )
