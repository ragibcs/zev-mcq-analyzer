"""Null explanation provider — used when LLM_PROVIDER=none.

The application must work perfectly with Jev alone; this provider makes the
"no explanation" case explicit instead of throwing.
"""

from __future__ import annotations

from app.services.llm.base import ExplanationResult, LLMProvider


class NullLLMProvider(LLMProvider):
    name = "none"

    async def explain(
        self,
        question: str,
        options: list[tuple[str, str]],
        jev_result: dict,
    ) -> ExplanationResult:
        raise RuntimeError(
            "NullLLMProvider.explain() should never be called; "
            "the /explain endpoint must return 503 when LLM_PROVIDER=none."
        )
