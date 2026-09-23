"""Schemas for structured decision results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OptionProbability(BaseModel):
    option_id: str
    option_text: str
    probability: float = Field(ge=0.0, le=1.0)


class DecisionResult(BaseModel):
    """Normalized decision output — provider-agnostic.

    ``predicted_option`` is the highest-probability option id.
    ``confidence`` is the provider's own calibrated confidence value, NOT
    restated as a guarantee of correctness.
    """

    predicted_option: str
    confidence: float = Field(ge=0.0, le=1.0)
    distribution: list[OptionProbability]
    provider: str
    model: str | None = None  # e.g. "jev-1.13.0" (the versioned id that answered)
