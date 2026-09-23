"""Jev (TypeSafe AI) decision provider — the primary decision engine.

Verified against the official TypeSafe AI REST API (September 2026):

    POST {JEV_BASE_URL}/systemone            (default base: https://api.typesafe.ai/v1)
    Authorization: Bearer <TYPESAFE_API_KEY>
    Content-Type: application/json

    body: {
      "model": "jev-latest",
      "state":  <string | object>,                       # what to judge
      "questions": {
        "<question_id>": {
          "type": "choice",
          "instructions": "<full question text>",
          "criteria": {"<option_key>": "<option description>", ...}
        }
      }
    }

    response: {
      "model": "jev-1.13.0",
      "answers": {
        "<question_id>": {
          "type": "choice",
          "choice": "<winning option_key>",
          "probabilities": {"<option_key>": 0.0..1.0, ...},
          "confidence": 0.0..1.0
        }
      },
      "usage": {"input_tokens": int, "output_tokens": int}
    }

    errors: 401 unauthorized · 422 validation · 429 rate limit · 529 overloaded
    (429/529 and network timeouts are retryable; everything else is not)

Notes
-----
* ``confidence`` is Jev's own calibrated field (shape of the distribution),
  distinct from the max probability. We surface both and never conflate them.
* We never fabricate probabilities: any missing option, malformed value, or
  unexpected payload raises :class:`JevProviderError` and is logged.
* Docs: https://docs.typesafe.ai · Console/keys: https://console.typesafe.ai
  Jev is also reachable via Vercel AI Gateway as ``typesafe-ai/jev``.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, JevProviderError
from app.core.logging import get_logger
from app.schemas.common import Option
from app.services.jev.base import DecisionProvider
from app.services.jev.schemas import DecisionResult, OptionProbability

logger = get_logger(__name__)

_RETRYABLE_STATUS = {429, 529}

# Option keys must be valid JSON object keys; we use safe identifiers (opt_a…)
_KEY_SAFE = re.compile(r"[^a-z0-9_]+")


def _option_key(option: Option) -> str:
    """Stable, safe key for an option (Jev criteria keys + JSON object keys)."""
    key = _KEY_SAFE.sub("_", option.id.strip().lower()).strip("_")
    if not key:
        key = f"anon_{abs(hash(option.id)) % 10_000}"
    # Prefix avoids collisions with reserved words and keeps keys unambiguous.
    return f"opt_{key}"


class JevDecisionProvider(DecisionProvider):
    """Adapter for the TypeSafe AI System One (Jev) REST API."""

    name = "jev"

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.jev_api_key:
            raise ConfigurationError(
                "JEV_API_KEY is not set. Get a key at https://console.typesafe.ai "
                "and add it to backend/.env."
            )
        self._base_url = self._settings.jev_base_url.rstrip("/")
        # Optional injection point for tests (httpx.MockTransport).
        self._transport = transport

    # ── DecisionProvider ───────────────────────────────────────────────

    async def analyze_mcq(
        self,
        question: str,
        options: list[Option],
    ) -> DecisionResult:
        payload = self._build_request(question, options)
        response_body = await self._post_systemone(payload)
        return self._parse_response(response_body, options)

    # ── Request building ───────────────────────────────────────────────

    def _build_request(self, question: str, options: list[Option]) -> dict[str, Any]:
        if len(options) < 2:
            raise JevProviderError("At least two options are required.")
        if len(options) > 255:
            # Jev Choice supports up to 255 options.
            raise JevProviderError("Jev Choice supports at most 255 options.")

        criteria: dict[str, str] = {}
        option_by_key: dict[str, Option] = {}
        for option in options:
            key = _option_key(option)
            if key in criteria:
                raise JevProviderError(f"Duplicate option identifier: {option.id!r}.")
            # Criteria describe what belongs to the option — the option text
            # itself, with the question id kept in the instructions.
            criteria[key] = option.text
            option_by_key[key] = option

        state = {
            "question": question,
            # Options are already in the Choice criteria; sending the letter
            # list in the state as well keeps the mapping unambiguous.
            "options": [f"{o.id}. {o.text}" for o in options],
        }

        return {
            "model": self._settings.jev_model,
            "state": state,
            "questions": {
                "mcq_answer": {
                    "type": "choice",
                    "instructions": (
                        "Which of the predefined options in `options` is the "
                        "correct answer to `question`?"
                    ),
                    "criteria": criteria,
                }
            },
        }

    # ── HTTP ───────────────────────────────────────────────────────────

    async def _post_systemone(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._settings.jev_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.jev_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/systemone", json=payload, headers=headers
                )
        except httpx.TimeoutException as exc:
            logger.error("Jev request timed out", extra={"data": {"base_url": self._base_url}})
            raise JevProviderError(
                "Jev request timed out.", transient=True
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("Jev network error", extra={"data": {"error": type(exc).__name__}})
            raise JevProviderError(
                "Jev service is unreachable.", transient=True
            ) from exc

        if response.status_code in _RETRYABLE_STATUS:
            raise JevProviderError(
                f"Jev is temporarily unavailable (HTTP {response.status_code}).",
                status_code=response.status_code,
                transient=True,
            )
        if response.status_code == 401:
            raise JevProviderError(
                "Jev rejected the API key (HTTP 401). Check JEV_API_KEY.",
                status_code=401,
            )
        if response.status_code == 422:
            # 422 = request failed Jev-side validation; the body names the field.
            detail = self._safe_detail(response)
            logger.error(
                "Jev validation error",
                extra={"data": {"detail": detail[:300]}},
            )
            raise JevProviderError(
                "Jev rejected the request payload (HTTP 422).",
                status_code=422,
            )
        if response.status_code != 200:
            raise JevProviderError(
                f"Jev request failed (HTTP {response.status_code}).",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise JevProviderError("Jev returned a malformed response.") from exc

    @staticmethod
    def _safe_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        return str(data.get("error") or data.get("detail") or data)[:300]

    # ── Response parsing ───────────────────────────────────────────────

    def _parse_response(
        self, body: dict[str, Any], options: list[Option]
    ) -> DecisionResult:
        answers = body.get("answers")
        if not isinstance(answers, dict) or "mcq_answer" not in answers:
            logger.error(
                "Jev response missing answers",
                extra={"data": {"keys": sorted(body.keys())}},
            )
            raise JevProviderError("Jev returned an unexpected response structure.")

        answer = answers["mcq_answer"]
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            logger.error(
                "Jev answer is not a choice",
                extra={"data": {"type": answer.get("type") if isinstance(answer, dict) else None}},
            )
            raise JevProviderError("Jev returned an unexpected answer type.")

        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or not probabilities:
            raise JevProviderError("Jev did not return a probability distribution.")

        # Map back to original option ids; every option must be present and
        # every value must be a real number in [0, 1]. No defaults, no filling.
        distribution: list[OptionProbability] = []
        for option in options:
            key = _option_key(option)
            if key not in probabilities:
                logger.error(
                    "Jev distribution missing an option",
                    extra={"data": {"missing_option": option.id}},
                )
                raise JevProviderError(
                    f"Jev distribution is missing option {option.id!r}."
                )
            value = probabilities[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                logger.error(
                    "Jev probability is not numeric",
                    extra={"data": {"option": option.id}},
                )
                raise JevProviderError(
                    f"Jev returned a non-numeric probability for {option.id!r}."
                )
            if not 0.0 <= float(value) <= 1.0:
                raise JevProviderError(
                    f"Jev probability out of range for {option.id!r}: {value}"
                )
            distribution.append(
                OptionProbability(
                    option_id=option.id,
                    option_text=option.text,
                    probability=round(float(value), 6),
                )
            )

        confidence = answer.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            # Confidence is a separate calibrated field; if absent we fall back
            # to the max probability and say so via `model`/docs, never invent.
            confidence = max(p.probability for p in distribution)

        chosen = answer.get("choice")
        if not isinstance(chosen, str):
            raise JevProviderError("Jev did not report a chosen option.")
        # Normalize the chosen key back to the original option id.
        predicted = next(
            (o.id for o in options if _option_key(o) == chosen), None
        )
        if predicted is None:
            # The chosen value must be one of the keys we sent; anything else
            # means the API contract changed.
            logger.error(
                "Jev chose an unknown option",
                extra={"data": {"choice": chosen}},
            )
            raise JevProviderError("Jev chose an option outside the provided set.")

        model = body.get("model") if isinstance(body.get("model"), str) else None

        return DecisionResult(
            predicted_option=predicted,
            confidence=round(float(confidence), 6),
            distribution=distribution,
            provider=self.name,
            model=model,
        )
