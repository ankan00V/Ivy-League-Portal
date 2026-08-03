#!/usr/bin/env python3
"""Label existing interaction and telemetry rows with their true traffic provenance.

Every ranking metric depends on being able to tell a real student apart from a
seeded one. The discriminator is `traffic_type`, but rows written before that field
was enforced carry either nothing or an inherited default of "real". That is how
`docs/portfolio/real_traffic_rollout_readiness.md` came to report 260 "real"
impressions and a +13.8pp CTR win for the `ml` ranker while genuine non-seed traffic
was 1,402 impressions and zero clicks.

The code-side fixes stop new bad rows. This script fixes the rows already stored.

Seeded rows are identified by markers the seeders themselves write:

  - `bootstrap_ranking_pipeline.py` stamps `query` as "bootstrap-ab:<variant>:<topic>"
  - `seed_release_ml_gate_fixture.py` and `simulate_persona_traffic.py` write rows
    under experiment keys matching the --simulated-experiment-regex pattern

Anything matching is relabelled "simulated". Everything else is LEFT ALONE - this
script never promotes a row to "real". Guessing that an unlabelled row is genuine is
the exact mistake being corrected here, so unknown rows stay unknown and are simply
excluded from real-traffic queries by the filters in app/models/traffic.py.

Usage:
    python scripts/backfill_traffic_provenance.py            # dry run, prints counts
    python scripts/backfill_traffic_provenance.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pymongo import MongoClient  # noqa: E402

# Seeders stamp this prefix on every query they write.
BOOTSTRAP_QUERY_PREFIX = "^bootstrap-ab:"
DEFAULT_SIMULATED_EXPERIMENT_REGEX = "sim|fixture|release-gate|persona"


def _seeded_filter(*, experiment_regex: str) -> dict[str, Any]:
    """Match rows a seeder wrote, whatever they are currently labelled."""
    return {
        "$or": [
            {"query": {"$regex": BOOTSTRAP_QUERY_PREFIX}},
            {"experiment_key": {"$regex": experiment_regex, "$options": "i"}},
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist the changes.")
    parser.add_argument(
        "--simulated-experiment-regex",
        default=DEFAULT_SIMULATED_EXPERIMENT_REGEX,
        help="Case-insensitive regex over experiment_key that marks a seeded run.",
    )
    parser.add_argument("--limit-preview", type=int, default=8)
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGODB_URL")
    if not mongo_url:
        print("MONGODB_URL is not set", file=sys.stderr)
        return 2
    db = MongoClient(mongo_url)[os.environ.get("MONGODB_DB_NAME", "vidyaverse")]

    seeded = _seeded_filter(experiment_regex=args.simulated_experiment_regex)
    report: dict[str, Any] = {"applied": False, "collections": {}}

    for name in ("opportunity_interactions", "ranking_request_telemetry"):
        collection = db[name]
        total = collection.count_documents({})
        already_simulated = collection.count_documents({"traffic_type": "simulated"})
        labelled_real = collection.count_documents({"traffic_type": "real"})
        unlabelled = collection.count_documents(
            {"$or": [{"traffic_type": {"$exists": False}}, {"traffic_type": None}, {"traffic_type": ""}]}
        )
        # The rows that matter: seeded, but not currently labelled as such.
        mislabelled = collection.count_documents(
            {"$and": [seeded, {"traffic_type": {"$ne": "simulated"}}]}
        )
        # Real-looking rows that survive the relabel. This is the honest denominator.
        genuine_after = collection.count_documents(
            {"$and": [{"traffic_type": "real"}, {"$nor": [seeded]}]}
        )

        samples = [
            {
                "query": str(row.get("query") or "")[:48],
                "experiment_key": str(row.get("experiment_key") or "")[:32],
                "traffic_type": row.get("traffic_type"),
            }
            for row in collection.find(
                {"$and": [seeded, {"traffic_type": {"$ne": "simulated"}}]},
                {"query": 1, "experiment_key": 1, "traffic_type": 1},
            ).limit(max(0, args.limit_preview))
        ]

        report["collections"][name] = {
            "total_rows": total,
            "currently_labelled_real": labelled_real,
            "currently_labelled_simulated": already_simulated,
            "currently_unlabelled": unlabelled,
            "seeded_rows_to_relabel": mislabelled,
            "genuine_real_rows_after_backfill": genuine_after,
            "sample_rows_to_relabel": samples,
        }

    print(json.dumps(report, indent=2, default=str))

    total_to_change = sum(
        int(item["seeded_rows_to_relabel"]) for item in report["collections"].values()
    )
    print(f"\nRows to relabel simulated: {total_to_change}")
    print(
        "Rows are only ever demoted to 'simulated'. Nothing is promoted to 'real', "
        "and nothing is deleted."
    )

    if not args.apply:
        print("\nDry run. Re-run with --apply to persist.")
        return 0

    if total_to_change == 0:
        print("\nNothing to do.")
        return 0

    changed = 0
    for name in report["collections"]:
        result = db[name].update_many(
            {"$and": [seeded, {"traffic_type": {"$ne": "simulated"}}]},
            {"$set": {"traffic_type": "simulated"}},
        )
        changed += int(result.modified_count)
        print(f"{name}: relabelled {result.modified_count} rows")

    print(f"\nRelabelled {changed} rows as simulated.")
    print(
        "Re-run the readiness gate to see the honest picture:\n"
        "  python backend/scripts/check_real_traffic_rollout_readiness.py --days 14"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
