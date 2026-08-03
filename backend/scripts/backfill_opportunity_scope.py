#!/usr/bin/env python3
"""Retire active opportunities that the current ingestion gates would reject.

Applies the two gates that now run at ingestion to rows that were stored before
they existed:

  is_probable_opportunity_posting  - page furniture: nav links, help centres,
                                     login pages, salary pages, marketing, and
                                     newsroom articles about awards already won.
  is_in_scope_opportunity          - opportunity types the product does not
                                     serve. Scope is internships and adjacent
                                     student opportunities; scholarships,
                                     fellowships and standalone research grants
                                     are out.

Rows are retired by setting opportunity_status="removed", never deleted, so the
decision stays auditable and reversible if scope changes.

Usage:
    python scripts/backfill_opportunity_scope.py            # dry run
    python scripts/backfill_opportunity_scope.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.time import utc_now  # noqa: E402
from app.services.scraper import (  # noqa: E402
    is_in_scope_opportunity,
    is_probable_opportunity_posting,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the changes.")
    parser.add_argument("--limit-preview", type=int, default=15)
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL is not set", file=sys.stderr)
        return 2
    db = MongoClient(mongo_url)[os.environ.get("MONGODB_DB_NAME", "vidyaverse")]

    rows = list(
        db.opportunities.find(
            {"opportunity_status": "active"},
            {"title": 1, "url": 1, "source": 1, "opportunity_type": 1},
        )
    )

    doomed: list[dict] = []
    reasons: Counter[str] = Counter()
    for row in rows:
        record = {
            "title": row.get("title"),
            "url": row.get("url"),
            "opportunity_type": row.get("opportunity_type"),
        }
        if not is_probable_opportunity_posting(record):
            doomed.append(row)
            reasons["not_a_posting"] += 1
        elif not is_in_scope_opportunity(record):
            doomed.append(row)
            reasons["out_of_scope_type"] += 1

    report = {
        "active_scanned": len(rows),
        "to_retire": len(doomed),
        "reasons": dict(reasons),
        "by_source": dict(Counter(r.get("source") for r in doomed).most_common(10)),
        "applied": False,
    }
    print(json.dumps(report, indent=2, default=str))

    if doomed:
        print("\nSample:")
        for row in doomed[: args.limit_preview]:
            print(f"  - {str(row.get('title'))[:66]}  [{row.get('source')}]")

    if not args.apply:
        print("\nDry run. Re-run with --apply to persist.")
        return 0

    now = utc_now().replace(tzinfo=None)
    result = db.opportunities.update_many(
        {"_id": {"$in": [row["_id"] for row in doomed]}},
        {"$set": {"opportunity_status": "removed", "updated_at": now}},
    )
    print(f"\nRetired {result.modified_count} rows (opportunity_status='removed').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
