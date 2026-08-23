#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.scraper import (  # noqa: E402
    GENERIC_PORTAL_LISTINGS,
    UNSTOP_CATEGORIES,
    merged_portal_listings,
    freshersworld_scraper,
    generic_portal_scraper,
    greenhouse_scraper,
    hack2skill_scraper,
    indeed_india_scraper,
    internshala_scraper,
    naukri_scraper,
    unstop_scraper,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(*, enabled: bool, count: int, error: str | None) -> str:
    if not enabled:
        return "disabled"
    if error:
        return "error"
    if count > 0:
        return "ok"
    return "empty"


async def _run_sync(label: str, fn: Any, *args: Any, timeout: float, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], list):
            items, errors = result
            return {
                "source": label,
                "status": _status(enabled=True, count=len(items), error="; ".join(errors) if errors and not items else None),
                "count": len(items),
                "errors": errors,
                "elapsed_ms": elapsed_ms,
                "sample_titles": [str(row.get("title") or "")[:120] for row in items[:3]],
            }
        items = list(result or [])
        return {
            "source": label,
            "status": _status(enabled=True, count=len(items), error=None),
            "count": len(items),
            "errors": [],
            "elapsed_ms": elapsed_ms,
            "sample_titles": [str(row.get("title") or "")[:120] for row in items[:3]],
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "source": label,
            "status": "error",
            "count": 0,
            "errors": [str(exc)],
            "traceback": traceback.format_exc(limit=3),
            "elapsed_ms": elapsed_ms,
            "sample_titles": [],
        }


async def audit_all(*, max_items: int, timeout_seconds: float, include_disabled: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    for category in UNSTOP_CATEGORIES:
        rows.append(
            await _run_sync(
                f"unstop:{category}",
                unstop_scraper.fetch_unstop_opportunities,
                category,
                max_items,
                timeout=timeout_seconds,
            )
        )

    core_jobs: list[tuple[str, Any]] = [
        ("naukri", naukri_scraper.fetch_it_jobs),
        ("internshala", internshala_scraper.fetch_live_opportunities),
        ("hack2skill", hack2skill_scraper.fetch_live_opportunities),
        ("freshersworld", freshersworld_scraper.fetch_live_opportunities),
        ("indeed_india", indeed_india_scraper.fetch_live_opportunities),
        ("greenhouse", greenhouse_scraper.fetch_live_opportunities),
    ]
    for label, fn in core_jobs:
        rows.append(await _run_sync(label, fn, max_items, timeout=timeout_seconds))

    for config in merged_portal_listings():
        source = str(config.get("source") or "").strip().lower()
        enabled = bool(config.get("enabled", True))
        if not source:
            continue
        if not enabled and not include_disabled:
            rows.append(
                {
                    "source": source,
                    "label": config.get("label"),
                    "status": "disabled",
                    "count": 0,
                    "errors": [],
                    "enabled": False,
                    "disabled_reason": config.get("disabled_reason"),
                    "listings": config.get("listings") or [],
                }
            )
            continue
        row = await _run_sync(
            source,
            generic_portal_scraper.fetch_live_opportunities,
            source,
            max_items,
            timeout=timeout_seconds,
        )
        row["label"] = config.get("label")
        row["enabled"] = enabled
        row["disabled_reason"] = config.get("disabled_reason")
        row["listings"] = config.get("listings") or []
        if not enabled:
            row["status"] = "disabled_probe"
        rows.append(row)

    summary = {
        "generated_at": _utcnow(),
        "max_items": max_items,
        "timeout_seconds": timeout_seconds,
        "include_disabled": include_disabled,
        "totals": {
            "sources": len(rows),
            "ok": sum(1 for row in rows if row.get("status") == "ok"),
            "empty": sum(1 for row in rows if row.get("status") == "empty"),
            "error": sum(1 for row in rows if row.get("status") == "error"),
            "disabled": sum(1 for row in rows if row.get("status") == "disabled"),
            "disabled_probe": sum(1 for row in rows if row.get("status") == "disabled_probe"),
        },
        "rows": rows,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit all configured scraper sources.")
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--include-disabled", action="store_true", default=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_ROOT / "benchmarks" / "scraper_source_audit.json",
    )
    args = parser.parse_args()

    report = asyncio.run(
        audit_all(
            max_items=max(1, args.max_items),
            timeout_seconds=max(10.0, args.timeout_seconds),
            include_disabled=bool(args.include_disabled),
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    totals = report["totals"]
    print(json.dumps(totals, indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
