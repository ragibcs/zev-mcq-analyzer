"""Application settings.

All secrets are read from the environment (optionally via a local ``.env`` file).
Secrets are never logged and never returned by the API.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_DECISION_PROVIDERS = ("jev",)
SUPPORTED_LLM_PROVIDERS = ("openrouter", "vercel", "none")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Decision engine ────────────────────────────────────────────────
    decision_provider: str = "jev"

    # ── Jev (TypeSafe AI System One model) ─────────────────────────────
    # REST API verified 2026-09: POST {base_url}/systemone
    #   Authorization: Bearer <key>
    #   body: {"model": "jev-latest", "state": {...}, "questions": {...}}
    # docs: https://docs.typesafe.ai — console.typesafe.ai for API keys.
    jev_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_base_url: str = "https://api.typesafe.ai/v1"
    jev_timeout_seconds: float = 15.0

    # ── Explanation (LLM) provider ─────────────────────────────────────
    llm_provider: str = "none"

    # OpenRouter — OpenAI-compatible: POST {base_url}/chat/completions
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Vercel AI Gateway — OpenAI-compatible: POST {base_url}/chat/completions
    vercel_ai_gateway_api_key: str = ""
    vercel_ai_gateway_model: str = ""
    vercel_ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"

    # ── Application ────────────────────────────────────────────────────
    cors_origins: str = ""
    log_level: str = "INFO"
    api_key: str = ""  # optional shared-secret auth for the backend itself

    # Security limits
    max_question_chars: int = 8000
    max_option_chars: int = 1000
    max_options: int = 255
    max_body_bytes: int = 65536
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    request_timeout_seconds: float = 20.0

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw or raw == "*":
            return []
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
