#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database
from app.models.opportunity_interaction import OpportunityInteraction
from app.services.interaction_service import SignalStrengthCalculator


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = await init_database()
    calculator = SignalStrengthCalculator()
    scanned = 0
    updated = 0
    by_event: dict[str, int] = {}
    try:
        query = OpportunityInteraction.find_many(
            {
                "$or": [
                    {"reward": {"$exists": False}},
                    {"reward": {"$gte": 0.0, "$lte": 0.0}},
                ]
            }
        ).sort("-created_at")
        if args.limit:
            query = query.limit(max(1, int(args.limit)))
        rows = await query.to_list()
        for row in rows:
            scanned += 1
            event_type = str(row.event_type or row.interaction_type or "view").strip().lower()
            next_reward = calculator.reward(
                event_type=event_type,
                dwell_time_ms=row.dwell_time_ms,
                scroll_depth=row.scroll_depth,
            )
            if next_reward == float(row.reward or 0.0):
                continue
            if not args.dry_run:
                row.reward = next_reward
                await row.save()
            updated += 1
            by_event[event_type] = by_event.get(event_type, 0) + 1
    finally:
        client.close()

    return {
        "status": "ok",
        "dry_run": bool(args.dry_run),
        "scanned_zero_reward_rows": scanned,
        "updated": updated,
        "updated_by_event_type": by_event,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill interaction rewards from canonical event types.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
