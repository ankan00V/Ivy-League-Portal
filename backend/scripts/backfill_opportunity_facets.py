"""Populate role_track and feed_categories on existing opportunity rows.

Both were computed in Python at serialization time. Migration 004 turned them
into columns so the feed can filter and count in SQL and stop shipping the whole
corpus to the browser, but existing rows carry NULL until this runs.

Dry run by default, like every backfill in this directory. It only ever writes
the two facet columns and never touches listing content, status or timestamps.

    ./backend/venv/bin/python backend/scripts/backfill_opportunity_facets.py
    ./backend/venv/bin/python backend/scripts/backfill_opportunity_facets.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import init_database  # noqa: E402
from app.db.pg_documents import get_pool  # noqa: E402
from app.services.opportunity_placement import classify_placement  # noqa: E402
from app.services.role_classification import classify_role_track  # noqa: E402

BATCH = 500


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--all", action="store_true", help="reclassify every row, not just NULL ones")
    args = parser.parse_args()

    await init_database()
    pool = await get_pool()

    where = "" if args.all else "WHERE role_track IS NULL"
    tracks: Counter[str] = Counter()
    placements: Counter[str] = Counter()
    scanned = 0
    updates: list[tuple] = []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, title, description, tags, opportunity_type, location, work_mode, "
            f"source FROM app.opportunities {where}"
        )
        for row in rows:
            scanned += 1
            track = classify_role_track(
                title=row["title"], description=row["description"],
                tags=row["tags"], opportunity_type=row["opportunity_type"],
            )
            categories = classify_placement(
                location=row["location"], work_mode=row["work_mode"],
                title=row["title"], description=row["description"],
                source=row["source"],
            )
            tracks[track] += 1
            for category in categories:
                placements[category] += 1
            updates.append((track, list(categories), row["id"]))

        print(f"scanned {scanned} row(s){'' if args.all else ' with role_track IS NULL'}")
        print(f"  role_track      : {dict(tracks)}")
        print(f"  feed_categories : {dict(placements)}")

        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

        for start in range(0, len(updates), BATCH):
            chunk = updates[start:start + BATCH]
            await conn.executemany(
                "UPDATE app.opportunities SET role_track = $1, feed_categories = $2 WHERE id = $3",
                chunk,
            )
        print(f"\napplied to {len(updates)} row(s)")
        remaining = await conn.fetchval(
            "SELECT count(*) FROM app.opportunities WHERE role_track IS NULL"
        )
        print(f"rows still unclassified: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
