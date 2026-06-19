from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from beanie.odm.operators.find.comparison import In

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database
from app.core.time import utc_now
from app.models.opportunity import Opportunity
from app.services.recommendation_quality_gate import (
    aggregate_persona_results,
    run_live_recommendation_quality_gate,
)


def _safe_mode(value: str) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"baseline", "semantic", "ml", "ab"} else "ml"


async def _load_candidates(*, max_candidates: int, portals: list[str]) -> list[Opportunity]:
    filters: list[Any] = [
        Opportunity.lifecycle_status == "published",
        Opportunity.opportunity_status == "active",
    ]
    if portals:
        filters.append(In(Opportunity.portal_category, portals))

    candidates = (
        await Opportunity.find_many(*filters)
        .sort("-freshness_score", "-quality_score", "-last_seen_at")
        .limit(max(25, int(max_candidates)))
        .to_list()
    )
    if candidates:
        return candidates

    # Local/dev datasets may not have lifecycle metadata backfilled yet.
    return (
        await Opportunity.find_many()
        .sort("-freshness_score", "-quality_score", "-last_seen_at")
        .limit(max(25, int(max_candidates)))
        .to_list()
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Run live recommendation quality gates across representative cold-start personas."
    )
    parser.add_argument("--ranking-mode", type=str, default="ml", choices=["baseline", "semantic", "ml", "ab"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=300)
    parser.add_argument("--portal", action="append", default=[], help="Restrict to one or more portal_category values.")
    parser.add_argument("--min-persona-pass-rate", type=float, default=0.75)
    parser.add_argument("--min-mean-mrr", type=float, default=0.35)
    parser.add_argument("--max-p95-latency-ms", type=float, default=1500.0)
    parser.add_argument("--json-out", type=str, default="backend/benchmarks/recommendation_quality_gate.json")
    parser.add_argument("--fail-on-not-ready", action="store_true")
    parser.add_argument("--no-warmup", action="store_true", help="Measure cold-start semantic latency instead of hot-path latency.")
    args = parser.parse_args()

    client = await init_database()
    try:
        candidates = await _load_candidates(max_candidates=int(args.max_candidates), portals=list(args.portal or []))
        results = await run_live_recommendation_quality_gate(
            opportunities=candidates,
            ranking_mode=_safe_mode(args.ranking_mode),
            limit=max(1, int(args.limit)),
            warmup=not bool(args.no_warmup),
        )
        summary = aggregate_persona_results(
            results=results,
            min_persona_pass_rate=float(args.min_persona_pass_rate),
            min_mean_mrr=float(args.min_mean_mrr),
            max_p95_latency_ms=float(args.max_p95_latency_ms),
        )
        payload = {
            "generated_at": utc_now().isoformat(),
            "ranking_mode": _safe_mode(args.ranking_mode),
            "warmup_enabled": not bool(args.no_warmup),
            "candidate_count": len(candidates),
            "limit": max(1, int(args.limit)),
            "summary": summary,
            "personas": [
                {
                    "name": item.name,
                    "passed": item.passed,
                    "latency_ms": item.latency_ms,
                    "candidate_count": item.candidate_count,
                    "returned_count": item.returned_count,
                    "relevant_in_top_k": item.relevant_in_top_k,
                    "precision_at_k": item.precision_at_k,
                    "reciprocal_rank": item.reciprocal_rank,
                    "first_relevant_rank": item.first_relevant_rank,
                    "top_results": item.top_results,
                }
                for item in results
            ],
        }

        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "ok",
                    "ready": bool(summary.get("ready")),
                    "candidate_count": len(candidates),
                    "pass_rate": summary.get("pass_rate"),
                    "mean_mrr": summary.get("mean_mrr"),
                    "p95_latency_ms": summary.get("p95_latency_ms"),
                    "json": str(out_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.fail_on_not_ready and not bool(summary.get("ready")):
            return 2
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
