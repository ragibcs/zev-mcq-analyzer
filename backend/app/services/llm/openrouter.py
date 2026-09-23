"""OpenRouter explanation provider.

Verified against the official OpenRouter API (September 2026):
OpenAI-compatible endpoint ``POST https://openrouter.ai/api/v1/chat/completions``
with ``Authorization: Bearer <OPENROUTER_API_KEY>``. The model comes from
``OPENROUTER_MODEL`` (e.g. ``openai/gpt-4o-mini``) and is never hard-coded.
Docs: https://openrouter.ai/docs
"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError
from app.services.llm.base import ExplanationResult, LLMProvider
from app.services.llm.openai_compat import (
    EXPLAIN_SYSTEM,
    OpenAICompatClient,
    build_explanation,
    extract_choice,
    render_explain_user_prompt,
    render_pick_user_prompt,
)


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.openrouter_api_key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set (LLM_PROVIDER=openrouter)."
            )
        if not self._settings.openrouter_model:
            raise ConfigurationError(
                "OPENROUTER_MODEL is not set (LLM_PROVIDER=openrouter)."
            )
        self._client = OpenAICompatClient(
            provider_name="OpenRouter",
            api_key=self._settings.openrouter_api_key,
            model=self._settings.openrouter_model,
            base_url=self._settings.openrouter_base_url,
            settings=self._settings,
            transport=transport,
        )

    async def explain(
        self,
        question: str,
        options: list[tuple[str, str]],
        jev_result: dict,
    ) -> ExplanationResult:
        prompt = render_explain_user_prompt(question, options, jev_result)
        text = await self._client.complete(EXPLAIN_SYSTEM, prompt)
        return build_explanation(
            provider_name=self.name,
            model=self._client.model,
            text=text,
            question=question,
            options=options,
            jev_result=jev_result,
        )

    async def pick(
        self,
        question: str,
        options: list[tuple[str, str]],
    ) -> str | None:
        from app.services.llm.openai_compat import PICK_SYSTEM

        text = await self._client.complete(
            PICK_SYSTEM, render_pick_user_prompt(question, options), max_tokens=8
        )
        return extract_choice(text, [oid for oid, _ in options])
