"""Decision provider factory.

Keeps provider selection in one place so API routes never change when new
decision providers are added.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.errors import ConfigurationError
from app.services.jev.base import DecisionProvider
from app.services.jev.client import JevDecisionProvider


def get_decision_provider() -> DecisionProvider:
    settings = get_settings()
    if settings.decision_provider == "jev":
        return JevDecisionProvider(settings)
    raise ConfigurationError(
        f"Unsupported DECISION_PROVIDER: {settings.decision_provider!r}. "
        f"Supported: {', '.join(('jev',))}"
    )
