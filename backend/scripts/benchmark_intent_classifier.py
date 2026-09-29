"""Compare intent classifiers on our own queries, before trusting anyone's card.

Ask AI infers an intent for every question and, until the fallback in
`vector_service.search_by_vector`, applied it as a hard filter. The incumbent is
a linear head (or seed centroids) over query embeddings, measured here at 34/40
with all six misses reading an internship question as "research".

Laya (convaiinnovations/laya) is a candidate replacement: an encoder that answers
typed questions with probabilities trained against proper scoring rules, which is
the property the incumbent lacks - its confidence does not separate right from
wrong, so nothing downstream can gate on it.

Every number published about Laya is the publisher's own. This script exists so
the decision is made on this corpus's queries instead, and it reports calibration
alongside accuracy, because a filter needs to know when to stop trusting itself.

    python scripts/benchmark_intent_classifier.py                 # incumbent only
    python scripts/benchmark_intent_classifier.py --laya          # both
    python scripts/benchmark_intent_classifier.py --laya --laya-model convaiinnovations/laya

Laya is an optional dependency and is never imported unless --laya is passed:

    pip install laya
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATASET = Path(__file__).resolve().parents[1] / "app" / "data" / "intent_queries.json"

#: The four the router already understands. Criteria are written for a model that
#: has never seen this product, so they describe the student's goal rather than
#: naming our internal labels.
LAYA_QUESTION = {
    "intent": {
        "type": "choice",
        "instructions": "What is this student looking for?",
        "criteria": {
            "internships": "internships, jobs, placements, hiring for a role at a company",
            "research": "research positions, fellowships, lab work, PhD or postdoc places, academic projects",
            "scholarships": "scholarships, grants, funding, financial aid, fee waivers",
            "hackathons": "hackathons, coding contests, competitions, challenges, datathons",
        },
    }
}


def _load_queries() -> list[dict[str, str]]:
    payload = json.loads(DATASET.read_text())
    return list(payload["queries"])


def _report(name: str, rows: list[dict]) -> dict:
    """Accuracy, plus whether the score can be used to gate the filter.

    The gap between mean confidence on right and wrong answers is the number that
    matters here. The incumbent's is near zero, which is why the hard filter had
    to be relaxed on outcome rather than on score.
    """
    total = len(rows)
    correct = [row for row in rows if row["ok"]]
    wrong = [row for row in rows if not row["ok"]]
    latencies = sorted(row["ms"] for row in rows)

    print(f"\n=== {name} ===")
    print(f"accuracy        : {len(correct)}/{total} = {len(correct)/total:.3f}")
    if latencies:
        print(
            f"latency         : median {statistics.median(latencies):.1f} ms, "
            f"p90 {latencies[int(0.9 * (len(latencies) - 1))]:.1f} ms"
        )
    if correct and wrong:
        mean_right = statistics.mean(row["confidence"] for row in correct)
        mean_wrong = statistics.mean(row["confidence"] for row in wrong)
        print(f"mean confidence : {mean_right:.3f} when right, {mean_wrong:.3f} when wrong")
        print(f"separation      : {mean_right - mean_wrong:+.3f}  (near zero means unusable as a gate)")
    # Brier score against the one-hot truth, over the predicted label only.
    brier = statistics.mean(
        (row["confidence"] - (1.0 if row["ok"] else 0.0)) ** 2 for row in rows
    )
    print(f"brier (top-1)   : {brier:.4f}  (lower is better)")

    if wrong:
        print("misses:")
        for row in wrong:
            print(f"  {row['confidence']:.3f}  {row['got']:<12} != {row['expected']:<12} {row['query'][:56]}")

    confusions: dict[str, int] = {}
    for row in wrong:
        key = f"{row['expected']} -> {row['got']}"
        confusions[key] = confusions.get(key, 0) + 1
    if confusions:
        print("confusions:", ", ".join(f"{key} x{count}" for key, count in sorted(confusions.items())))

    return {"name": name, "accuracy": len(correct) / total, "brier": brier}


async def _run_incumbent(queries: list[dict[str, str]]) -> list[dict]:
    from app.bootstrap import init_database
    from app.services.nlp_service import nlp_service

    # The active model version lives in the database; without it the service
    # falls back to seed centroids and the comparison would not be measuring
    # what production runs.
    await init_database()

    rows = []
    for item in queries:
        started = time.perf_counter()
        result = await nlp_service.classify_intent(item["query"])
        elapsed = (time.perf_counter() - started) * 1000.0
        rows.append(
            {
                "query": item["query"],
                "expected": item["intent"],
                "got": result["intent"],
                "ok": result["intent"] == item["intent"],
                "confidence": float(result.get("confidence") or 0.0),
                "ms": elapsed,
                "kind": result.get("model_kind"),
            }
        )
    kinds = {row["kind"] for row in rows}
    print(f"incumbent model_kind: {', '.join(sorted(str(kind) for kind in kinds))}")
    return rows


def _run_laya(queries: list[dict[str, str]], model: str, device: str) -> list[dict]:
    import laya  # optional dependency, imported only when asked for

    agent = laya.load(model, device=device) if device else laya.load(model)

    rows = []
    for item in queries:
        started = time.perf_counter()
        result = agent.predict({"query": item["query"]}, LAYA_QUESTION)
        elapsed = (time.perf_counter() - started) * 1000.0
        answer = result["answers"]["intent"]
        got = answer["choice"]
        rows.append(
            {
                "query": item["query"],
                "expected": item["intent"],
                "got": got,
                "ok": got == item["intent"],
                "confidence": float(answer.get("confidence") or 0.0),
                "ms": elapsed,
                "kind": model,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laya", action="store_true", help="also evaluate Laya (needs `pip install laya`)")
    parser.add_argument("--laya-model", default="convaiinnovations/laya")
    parser.add_argument("--device", default="", help="e.g. cuda; default lets laya choose")
    parser.add_argument(
        "--skip-incumbent",
        action="store_true",
        help="evaluate only the candidate, for running from an environment that has "
        "laya installed but not this project's dependencies",
    )
    args = parser.parse_args()

    queries = _load_queries()
    print(f"dataset: {DATASET.relative_to(Path.cwd()) if DATASET.is_relative_to(Path.cwd()) else DATASET}")
    print(f"queries: {len(queries)} (5 real, the rest hand-written - indicative, not production traffic)")

    summaries = []
    if not args.skip_incumbent:
        summaries.append(_report("incumbent (nlp_service.classify_intent)", asyncio.run(_run_incumbent(queries))))

    if args.laya:
        try:
            summaries.append(
                _report(f"laya ({args.laya_model})", _run_laya(queries, args.laya_model, args.device))
            )
        except ImportError:
            print("\nlaya is not installed. `pip install laya` to include it.", file=sys.stderr)
            return 2

    if len(summaries) > 1:
        best = max(summaries, key=lambda row: row["accuracy"])
        print(
            f"\nhigher accuracy on this set: {best['name']} "
            f"({best['accuracy']:.3f}). 40 queries is a sample, not a verdict - "
            "a difference of one or two answers is noise."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
