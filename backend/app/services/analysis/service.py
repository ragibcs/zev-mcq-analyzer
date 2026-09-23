"""Analysis orchestration: Jev decision + optional LLM explanation.

Error semantics (spec §27):
- Jev unavailable        → no prediction is generated (HTTP 5xx to the client).
- LLM unavailable        → Jev result still valid; explanation endpoint fails
  explicitly with the provider name. No silent fallback, ever.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import ConfigurationError, JevProviderError, LLMProviderError
from app.core.logging import get_logger
from app.schemas.common import Option
from app.services.jev.base import DecisionProvider
from app.services.jev.schemas import DecisionResult
from app.services.llm.base import ExplanationResult, LLMProvider
from app.services.llm.null_provider import NullLLMProvider

logger = get_logger(__name__)


class AnalysisService:
    def __init__(
        self,
        decision_provider: DecisionProvider,
        llm_provider: LLMProvider,
    ) -> None:
        self._decision = decision_provider
        self._llm = llm_provider

    async def analyze(self, question: str, options: list[Option]) -> DecisionResult:
        try:
            return await self._decision.analyze_mcq(question, options)
        except ConfigurationError as exc:  # missing key etc. → provider failure
            raise JevProviderError(str(exc)) from exc

    async def explain(
        self,
        question: str,
        options: list[Option],
        jev_result: DecisionResult | dict[str, Any],
    ) -> ExplanationResult:
        if isinstance(self._llm, NullLLMProvider):
            raise LLMProviderError(
                "Explanation service is not configured (LLM_PROVIDER=none).",
                provider="none",
            )

        jev_dict: dict[str, Any]
        if isinstance(jev_result, DecisionResult):
            jev_dict = jev_result.model_dump()
        elif isinstance(jev_result, dict):
            jev_dict = jev_result
        else:
            raise LLMProviderError(
                "Invalid jev_result payload.", provider=self._llm.name
            )

        pairs = [(o.id, o.text) for o in options]
        try:
            return await self._llm.explain(question, pairs, jev_dict)
        except ConfigurationError as exc:
            raise LLMProviderError(str(exc), provider=self._llm.name) from exc
        except LLMProviderError:
            raise
        except Exception as exc:  # narrow safety net — never leak internals
            logger.error(
                "Unexpected explanation failure",
                extra={
                    "data": {
                        "provider": self._llm.name,
                        "error": type(exc).__name__,
                    }
                },
            )
            raise LLMProviderError(
                "Explanation provider failed.",
                provider=self._llm.name,
            ) from exc
