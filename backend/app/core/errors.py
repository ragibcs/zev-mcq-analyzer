"""Typed exceptions.

Every provider failure maps to one of these so API handlers can return
explicit, safe error messages without leaking secrets or internals.
"""

from __future__ import annotations


class JevAnalyzerError(Exception):
    """Base class for all application errors."""


class ConfigurationError(JevAnalyzerError):
    """The environment configuration is invalid or incomplete."""


class InvalidRequestError(JevAnalyzerError):
    """The incoming request failed validation."""


class JevProviderError(JevAnalyzerError):
    """The Jev decision provider failed or returned an unexpected payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient  # 429 / 529 / timeouts are retryable


class LLMProviderError(JevAnalyzerError):
    """The explanation (LLM) provider failed or returned an unexpected payload."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
