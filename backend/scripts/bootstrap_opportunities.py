#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("OPENAI_API_KEY", "")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database
from app.services.duplicate_detector import duplicate_detector
from app.services.embedding_pipeline import embedding_pipeline
from app.services.opportunity_quality_service import opportunity_quality_scorer
from app.services.scraper import run_scheduled_scrapers


def _source_summary(report: dict[str, Any]) -> dict[str, int]:
    totals = {"total_fetched": 0, "total_inserted": 0, "total_deduplicated": 0}
    for source in list(report.get("sources") or []):
        totals["total_fetched"] += int(source.get("fetched") or source.get("items_fetched") or 0)
        totals["total_inserted"] += int(source.get("inserted") or source.get("items_inserted") or 0)
        totals["total_deduplicated"] += int(source.get("deduplicated") or source.get("items_deduplicated") or 0)
    return totals


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = await init_database()
    try:
        scraper_report = await run_scheduled_scrapers(force=True)
        quality_report = await opportunity_quality_scorer.run_quality_pipeline(stale_days=0, limit=int(args.quality_limit or 10_000))
        dedup_report = await duplicate_detector.scan_existing(
            limit=int(args.dedup_limit or 10_000),
            execute=bool(args.execute_dedup),
            mark_duplicate_closed=bool(args.close_duplicates and args.execute_dedup),
        )
        embedding_report = await embedding_pipeline.rebuild_vector_index_if_stale(force=bool(args.force_embeddings))
        payload = {
            "status": "ok",
            "sources": str(args.sources),
            "max_per_source": int(args.max_per_source),
            **_source_summary(scraper_report),
            "scraper": scraper_report,
            "quality": quality_report,
            "deduplication": dedup_report,
            "embeddings": embedding_report,
        }
        return payload
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap opportunities by scraping, quality scoring, deduping, and embedding.")
    parser.add_argument("--sources", default="all", help="Currently supports all scheduled sources.")
    parser.add_argument("--max-per-source", type=int, default=200, help="Operational target; scraper-specific env caps still apply.")
    parser.add_argument("--quality-limit", type=int, default=10_000)
    parser.add_argument("--dedup-limit", type=int, default=10_000)
    parser.add_argument("--execute-dedup", action="store_true", help="Persist dedup merges. Default is report-only.")
    parser.add_argument("--close-duplicates", action="store_true", help="Close duplicate rows when --execute-dedup is used.")
    parser.add_argument("--force-embeddings", action="store_true")
    parser.add_argument("--json-out", default="backend/benchmarks/bootstrap_opportunities_latest.json")
    args = parser.parse_args()

    if str(args.sources).strip().lower() != "all":
        raise SystemExit("bootstrap_opportunities currently supports --sources=all; use env scraper caps for per-source limits.")

    payload = asyncio.run(_run(args))
    output = json.dumps(payload, indent=2, sort_keys=True, default=str)
    print(output)
    out_path = Path(args.json_out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
