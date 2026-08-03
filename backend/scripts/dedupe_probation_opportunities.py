#!/usr/bin/env python3
"""Collapse duplicate probation rows left by the pre-upsert ingestion path.

`_run_probation_cycle` used to insert every scraped row on every probation run
instead of upserting on (discovered_source_id, url). A source scraped N times
therefore accumulated N copies of its entire result set - the live collection
held 3,497 rows for 249 distinct URLs.

For each (discovered_source_id, url) group this keeps the row with the highest
`run_number` (falling back to the most recently created) and deletes the rest.
Probation rows are working state that is regenerated on the next probation
cycle, so collapsing them loses nothing; the survivor is kept rather than
rewriting so the retained `raw_payload` is a real observation.

Usage:
    python scripts/dedupe_probation_opportunities.py            # dry run
    python scripts/dedupe_probation_opportunities.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pymongo import MongoClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the deletions.")
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL is not set", file=sys.stderr)
        return 2
    db = MongoClient(mongo_url)[os.environ.get("MONGODB_DB_NAME", "vidyaverse")]

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in db.probation_opportunities.find(
        {}, {"discovered_source_id": 1, "url": 1, "run_number": 1, "created_at": 1}
    ):
        key = (str(row.get("discovered_source_id")), str(row.get("url") or ""))
        groups[key].append(row)

    doomed: list = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(
            key=lambda r: (int(r.get("run_number") or 0), str(r.get("created_at") or "")),
            reverse=True,
        )
        doomed.extend(row["_id"] for row in rows[1:])

    total = sum(len(rows) for rows in groups.values())
    report = {
        "total_rows": total,
        "distinct_groups": len(groups),
        "duplicates_to_delete": len(doomed),
        "rows_after": total - len(doomed),
        "applied": False,
    }
    print(json.dumps(report, indent=2))

    if not args.apply:
        print("\nDry run. Re-run with --apply to persist.")
        return 0

    deleted = 0
    for start in range(0, len(doomed), 1000):
        result = db.probation_opportunities.delete_many(
            {"_id": {"$in": doomed[start : start + 1000]}}
        )
        deleted += result.deleted_count
    print(f"\nDeleted {deleted} duplicate probation rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
