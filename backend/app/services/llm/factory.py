"""Explanation provider factory (spec §23)."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.services.llm.base import LLMProvider
from app.services.llm.null_provider import NullLLMProvider
from app.services.llm.openrouter import OpenRouterProvider
from app.services.llm.vercel_gateway import VercelGatewayProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "openrouter":
        return OpenRouterProvider(settings)
    if settings.llm_provider == "vercel":
        return VercelGatewayProvider(settings)
    if settings.llm_provider == "none":
        return NullLLMProvider()
    raise ConfigurationError(
        f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}. "
        "Supported: openrouter, vercel, none."
    )
