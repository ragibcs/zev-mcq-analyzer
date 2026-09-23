"""Decision provider abstraction.

Jev is the primary decision engine; this ABC keeps it behind an adapter so
future decision providers can be added without changing API routes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.common import Option
from app.services.jev.schemas import DecisionResult


class DecisionProvider(ABC):
    name: str

    @abstractmethod
    async def analyze_mcq(
        self,
        question: str,
        options: list[Option],
    ) -> DecisionResult:
        """Analyze an MCQ and return a probability distribution over options.

        Implementations MUST NOT fabricate probabilities; they return exactly
        what the underlying provider reports and fail explicitly otherwise.
        """
        raise NotImplementedError
