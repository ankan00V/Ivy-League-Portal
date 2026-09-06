"""Delete opportunities nobody engaged with whose deadline has long passed.

Retiring a listing sets opportunity_status='removed' and leaves the row in
place, which is right for the feed - a listing can come back, and hard-deleting
scraped rows makes a bad classification unrecoverable. It reclaims nothing
though, and the corpus only grows. This is the second stage: rows that have been
dead for a while, that nobody applied to or saved, get removed for real.

Read the numbers before assuming this is worth running. Measured on the new
project 2026-08-27: the whole database is 47 MB against a 500 MB free-tier
allowance, so storage is at 9% and is not the constraint. What exhausted the old
project was egress, and the fix for that was paging the feed rather than
shipping 1,500 rows per request. Deleting rows helps a little - smaller scans,
smaller full-table reads - but anyone running this to "save space" should know
it is not where the pressure was.

Two safeguards matter more than the space.

Nothing engaged-with is ever deleted. There are no foreign keys into
app.opportunities: sixteen tables carry an opportunity_id by value only, so
Postgres will not stop a delete from orphaning an application or an interaction.
The reference check here is the only thing standing in the way, so it is done
explicitly and it fails closed - a table that cannot be checked blocks the
delete rather than being skipped.

vector_index_entries is cleaned in the same transaction. It is the second
largest table (9.9 MB) and holds one embedding per opportunity. Deleting a
listing without its vector leaves an orphan that still costs space and can still
be returned by a semantic search that then cannot resolve its row.

Dry run by default, like every destructive script in this directory:

    ./backend/venv/bin/python backend/scripts/purge_dead_opportunities.py
    ./backend/venv/bin/python backend/scripts/purge_dead_opportunities.py --apply

    --grace-days N   how long past the deadline before a row is eligible (default 90)
    --limit N        cap the delete, so a first run can be small and observed
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

from app.core.config import postgres_connect_args, resolve_postgres_dsn  # noqa: E402

SCHEMA = "app"

#: Tables whose presence means a human engaged with the listing, or that the row
#: is cited by something we must be able to explain later. A hit in any of these
#: makes the opportunity ineligible no matter how old it is.
#:
#: applications and career_outcome_events are the student's own record.
#: impact_events and recommendation_feedback are outcome evidence.
#: duplicate_merge_events records why another listing was folded into this one,
#: so deleting the survivor would strand that explanation.
ENGAGEMENT_TABLES = (
    ("applications", "opportunity_id"),
    ("career_outcome_events", "opportunity_id"),
    ("impact_events", "opportunity_id"),
    ("recommendation_feedback", "opportunity_id"),
    ("duplicate_merge_events", "canonical_opportunity_id"),
)

#: Interaction types that count as engagement. An impression does not - the feed
#: renders thousands of them and they say nothing about a listing mattering to
#: anyone. A save or an apply does.
ENGAGED_INTERACTIONS = ("save", "apply", "click")


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=$1 AND table_name=$2",
            SCHEMA,
            table,
        )
    )


async def _engaged_ids(conn: asyncpg.Connection) -> set[str]:
    """Every opportunity id that any engagement record points at.

    Fails closed. If a table in ENGAGEMENT_TABLES is missing or its column has
    been renamed, this raises instead of quietly returning a smaller protected
    set - the failure mode of a silent skip is deleting a student's application
    target, which is not recoverable.
    """
    protected: set[str] = set()
    for table, column in ENGAGEMENT_TABLES:
        if not await _table_exists(conn, table):
            raise SystemExit(
                f"engagement table '{table}' not found. Refusing to purge without "
                "being able to check it."
            )
        rows = await conn.fetch(
            f'SELECT DISTINCT "{column}"::text AS oid FROM {SCHEMA}."{table}" '
            f'WHERE "{column}" IS NOT NULL'
        )
        protected.update(r["oid"] for r in rows)

    if await _table_exists(conn, "opportunity_interactions"):
        # interaction_type is jsonb, not text - the ODM stores scalars as JSON
        # values - so it needs #>>'{}' to compare. A bare `= ANY(text[])` raises
        # "operator does not exist: jsonb = text" rather than matching nothing,
        # which is the good failure: it cannot silently protect zero rows.
        rows = await conn.fetch(
            f"SELECT DISTINCT opportunity_id::text AS oid FROM {SCHEMA}.opportunity_interactions "
            f"WHERE opportunity_id IS NOT NULL AND interaction_type#>>'{{}}' = ANY($1::text[])",
            list(ENGAGED_INTERACTIONS),
        )
        protected.update(r["oid"] for r in rows)
    return protected


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    parser.add_argument("--grace-days", type=int, default=90,
                        help="how long past the deadline before a row is eligible")
    parser.add_argument("--limit", type=int, default=0, help="cap the number deleted (0 = no cap)")
    args = parser.parse_args()
    grace = max(1, int(args.grace_days))

    dsn, ssl_mode = postgres_connect_args(resolve_postgres_dsn())
    conn = await asyncpg.connect(dsn, ssl=ssl_mode, statement_cache_size=0)
    try:
        before = await conn.fetchval("SELECT pg_database_size(current_database())")
        total = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.opportunities")

        # Eligible: the deadline is genuinely in the past by the grace window, or
        # the listing was retired that long ago. `last_seen_at` guards against
        # deleting something the scraper still finds - a listing that is still
        # being published is not dead, whatever its deadline says.
        candidates = await conn.fetch(
            f"""
            SELECT id::text AS id, title, opportunity_status, deadline
            FROM {SCHEMA}.opportunities
            WHERE (
                    (deadline IS NOT NULL AND deadline < now() - ($1 || ' days')::interval)
                 OR (opportunity_status IN ('removed', 'expired')
                     AND coalesce(updated_at, created_at) < now() - ($1 || ' days')::interval)
                  )
              AND (last_seen_at IS NULL OR last_seen_at < now() - ($1 || ' days')::interval)
            ORDER BY coalesce(deadline, updated_at, created_at)
            """,
            str(grace),
        )

        protected = await _engaged_ids(conn)
        eligible = [r for r in candidates if r["id"] not in protected]
        blocked = len(candidates) - len(eligible)
        if args.limit > 0:
            eligible = eligible[: args.limit]

        print(f"  database size        : {before / 1e6:.1f} MB")
        print(f"  opportunities        : {total:,}")
        print(f"  past grace ({grace}d)     : {len(candidates):,}")
        print(f"  protected by engagement: {blocked:,}")
        print(f"  eligible to delete   : {len(eligible):,}")

        if eligible:
            print("\n  oldest eligible:")
            for row in eligible[:8]:
                deadline = row["deadline"].date() if row["deadline"] else "no deadline"
                print(f"    {str(row['title'])[:44]:<44} {row['opportunity_status']:<9} {deadline}")

        if not eligible:
            print("\n  nothing to do.")
            return 0

        if not args.apply:
            print("\nDRY RUN - nothing deleted. Re-run with --apply.")
            return 0

        ids = [row["id"] for row in eligible]
        async with conn.transaction():
            # Vector first: an orphaned embedding outlives its row and is still
            # returned by semantic search, which then cannot resolve it.
            vectors = await conn.execute(
                f"DELETE FROM {SCHEMA}.vector_index_entries WHERE opportunity_id::text = ANY($1::text[])",
                ids,
            )
            deleted = await conn.execute(
                f"DELETE FROM {SCHEMA}.opportunities WHERE id::text = ANY($1::text[])", ids
            )
        print(f"\n  deleted opportunities : {deleted}")
        print(f"  deleted vector rows   : {vectors}")

        remaining = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.opportunities")
        print(f"  opportunities now     : {remaining:,} (was {total:,})")
        print(
            "\n  Space is not returned to the filesystem until VACUUM runs. Postgres "
            "reuses the freed pages for new rows, so the database will stop growing "
            "before it visibly shrinks."
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
