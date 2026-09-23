"""Calibration and evaluation metrics.

All functions are pure and shared between the benchmark runner and the
calibration research mode. Sample-size caveats: with small samples these
metrics are noisy; the UI explicitly avoids making calibration-quality claims
from tiny datasets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

BUCKETS = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]


@dataclass
class BucketStats:
    count: int = 0
    correct: int = 0
    confidence_sum: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.count if self.count else 0.0

    @property
    def avg_confidence(self) -> float:
        return self.confidence_sum / self.count if self.count else 0.0


@dataclass
class EvaluationReport:
    questions: int
    accuracy: float
    avg_confidence: float
    brier: float
    log_loss: float
    ece: float
    buckets: dict[str, BucketStats] = field(default_factory=dict)


def _bucket_index(confidence: float) -> int:
    # 1.0 belongs in the last bucket.
    return min(int(confidence * 5), 4)


def evaluate(
    records: list[dict],
    *,
    prob_key: str = "probability",
    predicted_key: str = "predicted",
    answer_key: str = "answer",
) -> EvaluationReport:
    """Evaluate records shaped like:

    ``{"predicted": "B", "probability": 0.96, "answer": "B"}``

    where ``probability`` is the confidence assigned to the predicted option.
    """
    n = len(records)
    if n == 0:
        return EvaluationReport(
            questions=0,
            accuracy=0.0,
            avg_confidence=0.0,
            brier=0.0,
            log_loss=0.0,
            ece=0.0,
            buckets={b: BucketStats() for b in BUCKETS},
        )

    correct = 0
    confidence_sum = 0.0
    brier_sum = 0.0
    log_loss_sum = 0.0
    buckets: dict[str, BucketStats] = {b: BucketStats() for b in BUCKETS}

    for record in records:
        predicted = record[predicted_key]
        answer = record[answer_key]
        probability = float(record[prob_key])
        probability = min(max(probability, 1e-15), 1 - 1e-15)

        is_correct = 1.0 if predicted == answer else 0.0
        correct += is_correct
        confidence_sum += probability
        # Brier for a binary "was the top prediction right" formulation.
        brier_sum += (probability - is_correct) ** 2
        log_loss_sum += -(
            is_correct * math.log(probability)
            + (1 - is_correct) * math.log(1 - probability)
        )

        stats = buckets[BUCKETS[_bucket_index(probability)]]
        stats.count += 1
        stats.correct += is_correct
        stats.confidence_sum += probability

    return EvaluationReport(
        questions=n,
        accuracy=correct / n,
        avg_confidence=confidence_sum / n,
        brier=brier_sum / n,
        log_loss=log_loss_sum / n,
        ece=sum(
            (stats.count / n) * abs(stats.accuracy - stats.avg_confidence)
            for stats in buckets.values()
            if stats.count
        ),
        buckets=buckets,
    )
