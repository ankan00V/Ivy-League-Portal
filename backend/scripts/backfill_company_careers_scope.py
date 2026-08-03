#!/usr/bin/env python3
"""Retire company-careers rows that the corrected scope filter rejects.

The previous `_is_early_career` used plain substring containment, so "intern"
matched "International"/"Internet" and "campus"/"student" matched marketing and
navigation copy. That admitted rows such as "Internet Banking", "International
travel insurance", "Discounts for students and teachers" and bare
"campusrecruitment@aexp.com" into the student feed.

Rows are retired by setting `opportunity_status="removed"`, never deleted:
the deadline/expiry path already taught us that destroying rows loses evidence
and is unrecoverable. Retired rows stay auditable and can be revived if the
filter is tuned again.

Usage:
    python scripts/backfill_company_careers_scope.py            # dry run
    python scripts/backfill_company_careers_scope.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.time import utc_now  # noqa: E402
from app.services.company_careers_intelligence import _is_early_career  # noqa: E402

RETIRED_STATUSES = {"expired", "filled", "removed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the changes. Without this flag the script only reports.",
    )
    parser.add_argument(
        "--source-prefix",
        default="company_careers",
        help="Only consider opportunities whose source matches this prefix.",
    )
    parser.add_argument("--limit-preview", type=int, default=25)
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL is not set", file=sys.stderr)
        return 2
    db_name = os.environ.get("MONGODB_DB_NAME", "vidyaverse")

    client = MongoClient(mongo_url)
    db = client[db_name]

    query = {"source": {"$regex": args.source_prefix}}
    rows = list(
        db.opportunities.find(
            query,
            {"title": 1, "description": 1, "tags": 1, "source": 1, "opportunity_status": 1},
        )
    )

    rejected = []
    for row in rows:
        status = str(row.get("opportunity_status") or "active").strip().lower()
        if status in RETIRED_STATUSES:
            continue
        candidate = {
            "title": row.get("title"),
            "description": row.get("description"),
            "tags": row.get("tags") or [],
        }
        if not _is_early_career(candidate):
            rejected.append(row)

    report = {
        "scanned": len(rows),
        "already_retired": sum(
            1
            for r in rows
            if str(r.get("opportunity_status") or "active").strip().lower() in RETIRED_STATUSES
        ),
        "to_retire": len(rejected),
        "applied": False,
    }

    print(json.dumps(report, indent=2))
    print("\nSample of rows that would be retired:")
    for row in rejected[: args.limit_preview]:
        print(f"  - {str(row.get('title'))[:70]}  [{row.get('source')}]")

    if not args.apply:
        print("\nDry run. Re-run with --apply to persist.")
        return 0

    now = utc_now().replace(tzinfo=None)
    result = db.opportunities.update_many(
        {"_id": {"$in": [row["_id"] for row in rejected]}},
        {"$set": {"opportunity_status": "removed", "updated_at": now}},
    )
    report["applied"] = True
    report["modified"] = result.modified_count
    print(f"\nRetired {result.modified_count} rows (opportunity_status='removed').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
