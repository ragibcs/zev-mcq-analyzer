"""Explanation (LLM) provider abstraction.

LLMs are never the primary MCQ probability engine. They only explain /
interpret the Jev result and can never modify its probabilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ExplanationResult(BaseModel):
    """Normalized explanation output — provider-agnostic.

    ``restated_*`` fields are copied from the Jev result on purpose: the
    explanation layer cannot change the prediction, only describe it.
    """

    summary: str
    per_option: dict[str, str]  # option_id -> explanation of that option
    provider: str  # "openrouter" | "vercel" | "none"
    model: str | None = None
    restated_prediction: str | None = None
    restated_confidence_pct: str | None = None
    meta: dict[str, Any] | None = None


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def explain(
        self,
        question: str,
        options: list[tuple[str, str]],  # (id, text) pairs
        jev_result: dict,
    ) -> ExplanationResult:
        """Explain an existing Jev result.

        Implementations MUST NOT modify or reinterpret the Jev probabilities;
        the explanation describes the decision, it does not replace it.
        """
        raise NotImplementedError

    async def pick(
        self,
        question: str,
        options: list[tuple[str, str]],
    ) -> str | None:
        """LLM-only option choice for the research comparison mode (§20).

        Optional: only used by the benchmark/comparison tooling. Returns the
        chosen option id, or None when the provider cannot answer. This never
        feeds back into Jev results.
        """
        raise NotImplementedError("This provider does not support pick().")
