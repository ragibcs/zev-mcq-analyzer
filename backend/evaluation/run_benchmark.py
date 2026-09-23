"""Benchmark runner.

Usage:
    python -m backend.evaluation.run_benchmark [--limit N] [--provider jev|llm|both]

Loads ``data/mcq_benchmark.json``, runs the configured providers, and reports
accuracy, confidence, Brier, log loss, ECE and bucket stats. For ``--provider
llm`` the LLM's chosen option is measured WITHOUT touching Jev probabilities;
for ``both`` the two are reported separately (spec §20: never merge scores).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow `python -m backend.evaluation.run_benchmark` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.errors import JevAnalyzerError, LLMProviderError
from app.schemas.common import Option
from app.services.jev.factory import get_decision_provider
from app.services.llm.factory import get_llm_provider
from evaluation.metrics import BUCKETS, evaluate

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "mcq_benchmark.json"


def load_dataset(path: Path = DATASET) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


async def run_jev(items: list[dict], limit: int | None = None) -> list[dict]:
    provider = get_decision_provider()
    records: list[dict] = []
    for item in items[:limit] if limit else items:
        options = [Option(id=chr(65 + i), text=t) for i, t in enumerate(item["options"])]
        try:
            result = await provider.analyze_mcq(item["question"], options)
            records.append(
                {
                    "question": item["question"],
                    "predicted": result.predicted_option,
                    "probability": result.confidence,
                    "answer": item["answer"],
                    "category": item.get("category", "unknown"),
                }
            )
            print(f"  ✓ {result.predicted_option} ({result.confidence:.2f}) vs {item['answer']}")
        except JevAnalyzerError as exc:
            print(f"  ✗ skipped (provider error): {exc}")
            continue
    return records


async def run_llm(items: list[dict], limit: int | None = None) -> list[dict]:
    provider = get_llm_provider()
    if provider.name == "none":
        print("LLM_PROVIDER=none — skipping LLM evaluation.")
        return []
    records: list[dict] = []
    for item in items[:limit] if limit else items:
        options = [Option(id=chr(65 + i), text=t) for i, t in enumerate(item["options"])]
        pairs = [(o.id, o.text) for o in options]
        try:
            chosen = await provider.pick(item["question"], pairs)
            if chosen:
                records.append(
                    {
                        "question": item["question"],
                        "predicted": chosen,
                        "probability": None,  # LLM mode: accuracy only
                        "answer": item["answer"],
                        "category": item.get("category", "unknown"),
                        "agreement_with_jev": None,
                    }
                )
        except (JevAnalyzerError, LLMProviderError) as exc:
            print(f"  ✗ skipped (LLM error): {exc}")
            continue
    return records


async def run_both(items: list[dict], limit: int | None = None) -> tuple[list[dict], list[dict]]:
    """Run Jev and LLM separately; report agreement without merging scores."""
    jev_records = await run_jev(items, limit)
    llm_records = await run_llm(items, limit)
    jev_by_question = {r["question"]: r for r in jev_records}
    agreement = 0
    compared = 0
    for lr in llm_records:
        jr = jev_by_question.get(lr["question"])
        if jr:
            compared += 1
            lr["agreement_with_jev"] = lr["predicted"] == jr["predicted"]
            agreement += int(lr["agreement_with_jev"])
    if compared:
        print(
            f"\nAgreement (Jev vs LLM): {agreement}/{compared} = {agreement / compared:.1%}\n"
            "(reported separately — never merged into one score)"
        )
    return jev_records, llm_records


def print_report(title: str, records: list[dict]) -> None:
    usable = [r for r in records if r.get("probability") is not None]
    print(f"\n{title}\n{'─' * len(title)}")
    if not usable:
        if records:
            n = len(records)
            acc = sum(1 for r in records if r["predicted"] == r["answer"]) / n
            print(f"Questions: {n}   Accuracy (choice only): {acc:.1%}")
        else:
            print("No scored records.")
        return
    report = evaluate(usable)
    print(f"Questions: {report.questions}")
    print(f"Accuracy: {report.accuracy:.1%}")
    print(f"Average confidence: {report.avg_confidence:.1%}")
    print(f"Brier score: {report.brier:.4f}")
    print(f"Log loss: {report.log_loss:.4f}")
    print(f"ECE: {report.ece:.4f}")
    print("\nConfidence buckets:")
    for name in BUCKETS:
        stats = report.buckets[name]
        if stats.count:
            print(
                f"  {name:8} n={stats.count:4}  acc={stats.accuracy:5.1%}  "
                f"conf={stats.avg_confidence:5.1%}"
            )
    if len(usable) < 30:
        print(
            "\nNote: small sample — metrics are directional only; "
            "no calibration-quality claims should be made."
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description="MCQ benchmark runner")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", choices=["jev", "llm", "both"], default="jev")
    args = parser.parse_args()

    get_settings()  # validate env early
    items = load_dataset()
    print(f"MCQ Benchmark\n{'─' * 13}\nQuestions: {len(items)}\n")

    if args.provider == "jev":
        records = await run_jev(items, args.limit)
        print_report("Jev results", records)
    elif args.provider == "llm":
        records = await run_llm(items, args.limit)
        print_report("LLM results (accuracy only)", records)
    else:
        jev_records, llm_records = await run_both(items, args.limit)
        print_report("Jev results", jev_records)
        print_report("LLM results", llm_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
