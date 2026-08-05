#!/usr/bin/env python3
"""Remove profile fields we no longer collect from documents already in Mongo.

Data minimization, 2026-08-05. `Profile` stopped declaring gender, pronouns,
date_of_birth, and the address line1/landmark/pincode fields. Nothing read them —
they were collected, stored, and never used.

Dropping a field from the Pydantic model makes it invisible to the application but
does **not** remove it from Mongo. Every existing profile document still physically
holds the values until they are unset. That is the worst of both worlds: retained
personal data that no code path can even show a student. This script closes it.

Dry run by default, in line with the other backfills in this directory. Nothing is
written unless `--apply` is passed.

    ./backend/venv/bin/python backend/scripts/purge_minimized_profile_fields.py
    ./backend/venv/bin/python backend/scripts/purge_minimized_profile_fields.py --apply

`current_address_region` and `permanent_address_region` are deliberately NOT purged.
They are live ranking inputs — see
`app/services/personalization/feature_builder.py::_profile_location_tokens`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database  # noqa: E402
from app.models.profile import Profile  # noqa: E402
from app.services.telemetry_privacy import get_collection  # noqa: E402

#: Exactly the fields removed from the model. Kept as a literal list rather than
#: derived from the model, because "fields the model no longer has" is unbounded and
#: would happily unset something that was renamed rather than retired.
PURGE_FIELDS = (
    "gender",
    "pronouns",
    "date_of_birth",
    "current_address_line1",
    "current_address_landmark",
    "current_address_pincode",
    "permanent_address_line1",
    "permanent_address_landmark",
    "permanent_address_pincode",
)

#: Guard against a careless edit above: these are load-bearing and must never be
#: unset by this script.
PROTECTED_FIELDS = ("current_address_region", "permanent_address_region")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually unset the fields. Without this flag the script only reports.",
    )
    args = parser.parse_args()

    overlap = set(PURGE_FIELDS) & set(PROTECTED_FIELDS)
    if overlap:
        raise SystemExit(f"Refusing to run: {sorted(overlap)} are ranking inputs.")

    client = await init_database()
    try:
        collection = get_collection(Profile)

        counts = {
            field: await collection.count_documents({field: {"$exists": True}})
            for field in PURGE_FIELDS
        }
        affected = await collection.count_documents(
            {"$or": [{field: {"$exists": True}} for field in PURGE_FIELDS]}
        )

        report = {
            "mode": "apply" if args.apply else "dry-run",
            "documents_with_at_least_one_removed_field": affected,
            "per_field_counts": counts,
            "protected_fields_untouched": list(PROTECTED_FIELDS),
        }

        if args.apply and affected:
            result = await collection.update_many(
                {"$or": [{field: {"$exists": True}} for field in PURGE_FIELDS]},
                {"$unset": {field: "" for field in PURGE_FIELDS}},
            )
            report["documents_modified"] = int(getattr(result, "modified_count", 0) or 0)
            remaining = await collection.count_documents(
                {"$or": [{field: {"$exists": True}} for field in PURGE_FIELDS]}
            )
            report["documents_still_carrying_a_removed_field"] = remaining

        print(json.dumps(report, indent=2))
        if not args.apply:
            print("\nDry run. Re-run with --apply to unset these fields.", file=sys.stderr)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
