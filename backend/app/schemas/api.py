"""HTTP request/response schemas for the API layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Option  # reuse the domain option schema


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    options: list[Option] = Field(min_length=2, max_length=255)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class AnalyzeResponse(BaseModel):
    predicted_option: str
    confidence: float
    distribution: list[dict[str, Any]]
    provider: str
    model: str | None = None


class ExplainRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    options: list[Option] = Field(min_length=2, max_length=255)
    jev_result: dict[str, Any]

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class ExplainResponse(BaseModel):
    summary: str
    per_option: dict[str, str]
    provider: str
    model: str | None = None
    restated_prediction: str | None = None
    restated_confidence_pct: str | None = None


class ProvidersResponse(BaseModel):
    decision_provider: str
    llm_provider: str
    llm_available: bool


class ConfigResponse(BaseModel):
    decision_provider: str
    llm_provider: str
    jev_model: str
    limits: dict[str, int]
    # No secrets are ever included here.


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
