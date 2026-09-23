"""Vercel AI Gateway explanation provider.

Verified against the official Vercel AI Gateway docs (September 2026):
OpenAI-compatible endpoint ``POST https://ai-gateway.vercel.sh/v1/chat/completions``
with ``Authorization: Bearer <VERCEL_AI_GATEWAY_API_KEY>``. The model uses the
gateway routing syntax (e.g. ``openai/gpt-4o-mini``) and comes from
``VERCEL_AI_GATEWAY_MODEL``. Docs: https://vercel.com/docs/ai-gateway
"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError
from app.services.llm.base import ExplanationResult, LLMProvider
from app.services.llm.openai_compat import (
    EXPLAIN_SYSTEM,
    PICK_SYSTEM,
    OpenAICompatClient,
    build_explanation,
    extract_choice,
    render_explain_user_prompt,
    render_pick_user_prompt,
)


class VercelGatewayProvider(LLMProvider):
    name = "vercel"

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.vercel_ai_gateway_api_key:
            raise ConfigurationError(
                "VERCEL_AI_GATEWAY_API_KEY is not set (LLM_PROVIDER=vercel)."
            )
        if not self._settings.vercel_ai_gateway_model:
            raise ConfigurationError(
                "VERCEL_AI_GATEWAY_MODEL is not set (LLM_PROVIDER=vercel)."
            )
        self._client = OpenAICompatClient(
            provider_name="Vercel AI Gateway",
            api_key=self._settings.vercel_ai_gateway_api_key,
            model=self._settings.vercel_ai_gateway_model,
            base_url=self._settings.vercel_ai_gateway_base_url,
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
        text = await self._client.complete(
            PICK_SYSTEM, render_pick_user_prompt(question, options), max_tokens=8
        )
        return extract_choice(text, [oid for oid, _ in options])
