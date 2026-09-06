"""Copy the serving Postgres database into a new project, and prove it arrived.

Written for the Supabase project move: the old organisation exceeded its 5.5 GB
egress allowance and its grace period ends, so the schema and rows have to exist
somewhere else before the app is repointed.

Why not pg_dump. Supabase serves direct connections (db.<ref>.supabase.co:5432)
over IPv6 only, and this network has no IPv6 route - the address resolves and
then fails with "No route to host". The session pooler on 5432 times out too.
The transaction pooler on 6543 is the single reachable path to either project,
and pg_dump cannot use one: it needs session state pgbouncer does not carry.

So the copy runs over asyncpg with statement_cache_size=0, which is exactly how
the application already talks to the same pooler. Schema comes from the
migration files in migrations/neon rather than from a dump, so the target is
built the same way any other environment would be.

Direction is taken from two explicit environment variables rather than from
backend/.env, because .env holds the *current* database under the name the app
reads. Reusing it would mean editing live configuration before the copy exists,
and a mistake there points the running app at an empty database.

    export MIGRATE_SOURCE_DSN='postgresql://...old.../postgres'   # read from
    export MIGRATE_TARGET_DSN='postgresql://...new.../postgres'   # written to

Percent-encode any '@' in a password as '%40'. libpq splits the DSN at the first
'@', so an unescaped one silently truncates the password and surfaces as an
authentication failure rather than a parse error.

Dry run by default, like every other script in this directory:

    ./backend/venv/bin/python backend/scripts/migrate_postgres_project.py
    ./backend/venv/bin/python backend/scripts/migrate_postgres_project.py --apply

Verification is not the copy's own opinion of itself. After writing, this
reconnects to both databases and compares row counts table by table. A backfill
in this repo reported "applied to 2,290 rows" while writing nothing at all, so a
success message is not evidence; count(*) is.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

SCHEMA = "app"
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "neon"

#: Rows copied per round trip. Small enough that a single failure does not lose
#: much work, large enough that 2,000 opportunities is a handful of trips.
BATCH = 500

#: Tables whose rows can be regenerated or safely abandoned, offered behind
#: --skip-telemetry. They are the overwhelming majority by row count, and
#: reading them costs egress on the very project that ran out of it.
#:
#: Structure is still created - only the rows are skipped - so nothing has to be
#: re-migrated later to make the schema whole.
#:
#: What is lost, stated rather than implied: opportunity_interactions is the
#: impression and click log, which README records as one developer's traffic
#: rather than student traffic. feature_store_rows is derived from it by the
#: warehouse rebuild. scraper_run_logs is per-source scrape history, rebuilt on
#: the next run. None are student-facing and none feed the live feed. If the
#: ranking work later needs a real traffic baseline, do not skip these.
TELEMETRY_TABLES = (
    "opportunity_interactions",
    "feature_store_rows",
    "scraper_run_logs",
    "ranking_request_telemetry",
)


def _redact(dsn: str) -> str:
    """Host and database only. Never let a password reach stdout or a log."""
    return re.sub(r"//[^@]*@", "//***:***@", str(dsn or ""))


def _dsn(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(
            f"{name} is not set. Export both MIGRATE_SOURCE_DSN and "
            "MIGRATE_TARGET_DSN before running."
        )
    return value


async def _connect(dsn: str) -> asyncpg.Connection:
    # statement_cache_size=0 for the same reason the app sets it: pgbouncer in
    # transaction mode does not support asyncpg's cached prepared statements.
    return await asyncio.wait_for(
        asyncpg.connect(dsn, ssl="require", statement_cache_size=0), timeout=45
    )


async def _table_counts(conn: asyncpg.Connection) -> dict[str, int]:
    """Row count per table, counted rather than estimated.

    count(*) not reltuples: the planner statistic is approximate, and a
    migration that lost rows would still look plausible through it.
    """
    tables = [
        record["tablename"]
        for record in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = $1 ORDER BY tablename",
            SCHEMA,
        )
    ]
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = int(await conn.fetchval(f'SELECT count(*) FROM {SCHEMA}."{table}"') or 0)
    return counts


async def _columns(conn: asyncpg.Connection, table: str) -> list[str]:
    return [
        record["column_name"]
        for record in await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position",
            SCHEMA,
            table,
        )
    ]


async def _apply_schema(target: asyncpg.Connection) -> list[str]:
    """Build the target from the committed migrations, not from a dump.

    Executed whole-file rather than split on semicolons: the migrations contain
    dollar-quoted function bodies and inline comments, and a naive split would
    cut one in half. asyncpg's execute() accepts multiple statements.
    """
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        try:
            await target.execute(sql)
            applied.append(path.name)
        except Exception as exc:
            # IF NOT EXISTS guards mean a re-run is expected to be uneventful;
            # anything else is worth surfacing rather than swallowing.
            print(f"    {path.name}: {type(exc).__name__}: {str(exc)[:140]}")
    return applied


async def _copy_table(
    source: asyncpg.Connection, target: asyncpg.Connection, table: str, expected: int
) -> int:
    """Copy one table by shared column name, in batches. Returns rows written."""
    source_columns = await _columns(source, table)
    target_columns = set(await _columns(target, table))
    shared = [c for c in source_columns if c in target_columns]
    if not shared:
        print(f"    {table}: no shared columns, skipped")
        return 0

    quoted = ", ".join(f'"{c}"' for c in shared)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(shared)))
    insert = (
        f'INSERT INTO {SCHEMA}."{table}" ({quoted}) VALUES ({placeholders}) '
        f"ON CONFLICT DO NOTHING"
    )

    written = 0
    offset = 0
    while True:
        # Ordered by ctid so paging is stable without assuming a sortable key;
        # every table here has one, but not all of them share a column name.
        rows = await source.fetch(
            f'SELECT {quoted} FROM {SCHEMA}."{table}" ORDER BY ctid LIMIT {BATCH} OFFSET {offset}'
        )
        if not rows:
            break
        await target.executemany(insert, [tuple(r) for r in rows])
        written += len(rows)
        offset += BATCH
        if expected:
            print(f"    {table}: {written:,}/{expected:,}", end="\r", flush=True)
    return written


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the copy (default: dry run)")
    parser.add_argument(
        "--allow-nonempty-target",
        action="store_true",
        help="proceed even if the target already holds rows",
    )
    parser.add_argument(
        "--skip-telemetry",
        action="store_true",
        help="create the telemetry tables but do not copy their rows (see TELEMETRY_TABLES)",
    )
    args = parser.parse_args()

    source_dsn = _dsn("MIGRATE_SOURCE_DSN")
    target_dsn = _dsn("MIGRATE_TARGET_DSN")
    if source_dsn == target_dsn:
        raise SystemExit("source and target are the same DSN. Refusing to run.")

    print(f"source: {_redact(source_dsn)}")
    print(f"target: {_redact(target_dsn)}\n")

    source = await _connect(source_dsn)
    target = await _connect(target_dsn)
    try:
        source_counts = await _table_counts(source)
        if not source_counts:
            raise SystemExit(f"source has no tables in schema '{SCHEMA}'. Wrong database?")
        target_counts = await _table_counts(target)

        source_total = sum(source_counts.values())
        target_total = sum(target_counts.values())
        print(f"source: {len(source_counts)} tables, {source_total:,} rows")
        print(f"target: {len(target_counts)} tables, {target_total:,} rows")

        # Overwriting a database that already holds data is the one mistake here
        # that cannot be undone, so it takes a second explicit flag.
        if target_total > 0 and not args.allow_nonempty_target:
            raise SystemExit(
                f"\ntarget already holds {target_total:,} rows. If that is a stale "
                "copy you intend to add to, re-run with --allow-nonempty-target."
            )

        skipped = [t for t in TELEMETRY_TABLES if t in source_counts] if args.skip_telemetry else []
        skipped_rows = sum(source_counts[t] for t in skipped)
        to_copy = {t: n for t, n in source_counts.items() if t not in skipped}

        print("\nlargest tables:")
        for table, count in sorted(source_counts.items(), key=lambda kv: -kv[1])[:10]:
            marker = "   [structure only]" if table in skipped else ""
            print(f"  {table:<34} {count:,}{marker}")

        if skipped:
            print(
                f"\nskipping rows for {len(skipped)} telemetry table(s): "
                f"{skipped_rows:,} of {source_total:,} "
                f"({skipped_rows / source_total:.0%}). Copying {source_total - skipped_rows:,}."
            )

        if not args.apply:
            print(f"\nDRY RUN - nothing written. Re-run with --apply.")
            return 0

        print(f"\napplying schema from {MIGRATIONS_DIR.name}/ ...")
        applied = await _apply_schema(target)
        print(f"  applied {len(applied)} migration file(s)")

        created = await _table_counts(target)
        missing = [t for t in to_copy if t not in created]
        if missing:
            raise SystemExit(
                f"schema incomplete: {len(missing)} table(s) absent after migration, "
                f"e.g. {missing[:5]}. Refusing to copy into a partial schema."
            )

        print("\ncopying rows:")
        for table in sorted(to_copy, key=lambda t: -to_copy[t]):
            expected = to_copy[table]
            if expected == 0:
                continue
            written = await _copy_table(source, target, table, expected)
            print(f"    {table:<34} {written:,} rows written")

        print("\nverifying against the target, not the copy's own report:")
        after = await _table_counts(target)
        mismatches: list[str] = []
        for table, source_rows in sorted(source_counts.items()):
            # A deliberately skipped table is expected to arrive empty. Comparing
            # it against the source would report intended behaviour as data loss.
            expected = 0 if table in skipped else source_rows
            got = after.get(table)
            if got is None:
                mismatches.append(f"  MISSING  {table:<32} expected {expected:,}")
            elif got != expected:
                mismatches.append(f"  MISMATCH {table:<32} expected {expected:,}, got {got:,}")

        if mismatches:
            print("\n".join(mismatches))
            print(f"\n{len(mismatches)} table(s) did not match. The target is NOT a faithful copy.")
            return 1

        print(f"  all {len(source_counts)} tables match ({sum(after.values()):,} rows)")
        print(
            "\nCopy verified. The app still points at the source: update "
            "SUPABASE_DATABASE_URL in backend/.env to switch."
        )
        return 0
    finally:
        await source.close()
        await target.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
