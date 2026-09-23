"""Common domain schemas shared across providers."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Option(BaseModel):
    """A predefined MCQ answer option."""

    id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("id", "text")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
