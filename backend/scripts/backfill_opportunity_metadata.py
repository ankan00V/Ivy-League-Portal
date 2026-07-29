#!/usr/bin/env python3
"""Re-derive stipend and canonicalise opportunity_type on existing rows.

Two ingestion defects left the corpus worse than the parsers can now do:

- Stipend was populated on 0 of 364 active opportunities. The old patterns
  anchored the currency with \\b, but "₹" is a non-word character so \\b could
  never match before it, and there was no form for amount-then-currency, a
  labelled bare amount, lakh/LPA notation, or an explicit "unpaid".

- opportunity_type was canonicalised only on the employer and admin write
  paths, so scraped rows carried "Hackathon" and "Hackathons" (and
  Conference/Conferences) as distinct types. Filters and portal routing treat
  those as different, so a student filtering hackathons saw about half of them.

Only fills a missing stipend - an existing value is never overwritten, since a
source-provided figure is more trustworthy than one re-derived from prose.

Usage:
    python scripts/backfill_opportunity_metadata.py            # dry run
    python scripts/backfill_opportunity_metadata.py --apply
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

from pymongo import MongoClient, UpdateOne  # noqa: E402

from app.services.opportunity_visibility import canonical_opportunity_type  # noqa: E402
from app.services.scraper import _collapse_whitespace, _extract_stipend  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the changes.")
    parser.add_argument("--limit-preview", type=int, default=12)
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL is not set", file=sys.stderr)
        return 2
    db = MongoClient(mongo_url)[os.environ.get("MONGODB_DB_NAME", "vidyaverse")]

    operations: list[UpdateOne] = []
    stipend_found = 0
    type_changes: Counter[str] = Counter()
    stipend_examples: list[str] = []

    cursor = db.opportunities.find(
        {},
        {"title": 1, "description": 1, "eligibility": 1, "stipend": 1, "opportunity_type": 1},
    )
    scanned = 0
    for row in cursor:
        scanned += 1
        updates: dict[str, object] = {}

        if not _collapse_whitespace(row.get("stipend")):
            haystack = " ".join(
                _collapse_whitespace(row.get(field))
                for field in ("title", "description", "eligibility")
            )
            stipend = _extract_stipend(haystack)
            if stipend:
                updates["stipend"] = stipend
                stipend_found += 1
                if len(stipend_examples) < args.limit_preview:
                    stipend_examples.append(f"{str(row.get('title'))[:44]} -> {stipend}")

        raw_type = row.get("opportunity_type")
        if raw_type:
            canonical = canonical_opportunity_type(raw_type)
            if canonical and canonical != raw_type:
                updates["opportunity_type"] = canonical
                type_changes[f"{raw_type} -> {canonical}"] += 1

        if updates:
            operations.append(UpdateOne({"_id": row["_id"]}, {"$set": updates}))

    report = {
        "scanned": scanned,
        "rows_to_update": len(operations),
        "stipend_recovered": stipend_found,
        "type_changes": dict(type_changes),
        "applied": False,
    }
    print(json.dumps(report, indent=2))

    if stipend_examples:
        print("\nSample stipends recovered:")
        for line in stipend_examples:
            print(f"  {line}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to persist.")
        return 0

    modified = 0
    for start in range(0, len(operations), 500):
        result = db.opportunities.bulk_write(operations[start : start + 500], ordered=False)
        modified += result.modified_count
    print(f"\nUpdated {modified} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
