"""Copy the serving Postgres database into a new one, and prove it arrived.

Written for the Supabase project move: the old organisation exceeded its 5.5 GB
egress allowance and gets restricted, so the same schema and rows have to exist
somewhere else before the app is repointed.

Direction is taken from two explicit environment variables rather than from
backend/.env, because .env holds the *current* database under the name the app
reads. Reusing it would mean editing the live configuration before the copy has
happened, and a mistake there points the running app at an empty database.

    export MIGRATE_SOURCE_DSN='postgresql://...old.../postgres'   # read from
    export MIGRATE_TARGET_DSN='postgresql://...new.../postgres'   # written to

Use the DIRECT connections (port 5432), not the pooled ones (6543). pgbouncer in
transaction mode does not carry the session state pg_dump and psql rely on.

If a password contains '@', percent-encode it as '%40'. asyncpg and libpq split
the DSN at the first '@', so an unescaped one silently truncates the password and
surfaces as an authentication failure rather than a parse error.

Dry run by default, like every other script in this directory:

    ./backend/venv/bin/python backend/scripts/migrate_postgres_project.py
    ./backend/venv/bin/python backend/scripts/migrate_postgres_project.py --apply

Verification is not optional and not the copy's own opinion of itself. After the
restore this reconnects to both databases and compares row counts table by
table. A backfill in this repo reported "applied to 2,290 rows" while writing
nothing at all, so a script's success message is not evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg  # noqa: E402

SCHEMA = "app"

#: Tables whose rows can be regenerated or safely abandoned, offered behind
#: --skip-telemetry. They are 91% of the corpus by row count (91,815 of 101,046
#: measured 2026-08-26) and reading them costs egress on the very project that
#: ran out of it.
#:
#: Structure is still copied - only the rows are skipped - so nothing has to be
#: re-migrated later to make the schema whole.
#:
#: What is lost, stated rather than implied: opportunity_interactions is the
#: impression and click log, which README records as one developer's traffic
#: rather than student traffic. feature_store_rows is derived from it by the
#: warehouse rebuild. scraper_run_logs is per-source scrape history, rebuilt on
#: the next run. None of them are student-facing and none feed the live feed.
#: If the ranking work later needs a real traffic baseline, do not skip these.
TELEMETRY_TABLES = (
    "opportunity_interactions",
    "feature_store_rows",
    "scraper_run_logs",
    "ranking_request_telemetry",
)


def _redact(dsn: str) -> str:
    """Host and database only. Never let a password reach stdout or a log."""
    return re.sub(r"//[^@]*@", "//***:***@", str(dsn or ""))


def _require_tools() -> None:
    missing = [tool for tool in ("pg_dump", "psql") if not shutil.which(tool)]
    if missing:
        raise SystemExit(
            f"missing required tool(s): {', '.join(missing)}. "
            "Install the Postgres client (brew install postgresql)."
        )


def _dsn(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(
            f"{name} is not set. Export both MIGRATE_SOURCE_DSN and "
            "MIGRATE_TARGET_DSN as direct (port 5432) connection strings."
        )
    if ":6543/" in value:
        raise SystemExit(
            f"{name} points at the pooler (port 6543). Use the direct connection "
            "on 5432: pgbouncer does not support the session state pg_dump needs."
        )
    return value


async def _table_counts(dsn: str) -> dict[str, int]:
    """Row count per table in the app schema, read directly rather than estimated.

    count(*) not reltuples: the planner statistic is approximate and a migration
    that lost rows would still look plausible through it.
    """
    conn = await asyncpg.connect(dsn, ssl="require", statement_cache_size=0)
    try:
        tables = [
            record["tablename"]
            for record in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = $1 ORDER BY tablename",
                SCHEMA,
            )
        ]
        counts: dict[str, int] = {}
        for table in tables:
            counts[table] = int(
                await conn.fetchval(f'SELECT count(*) FROM {SCHEMA}."{table}"') or 0
            )
        return counts
    finally:
        await conn.close()


def _run(command: list[str], *, stdin=None, stdout=None) -> None:
    result = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{command[0]} failed:\n{result.stderr[-2000:]}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the copy (default: dry run)")
    parser.add_argument(
        "--allow-nonempty-target",
        action="store_true",
        help="proceed even if the target already holds rows (it will be overwritten)",
    )
    parser.add_argument(
        "--skip-telemetry",
        action="store_true",
        help=(
            "copy the structure of the high-volume telemetry tables but not their "
            "rows (see TELEMETRY_TABLES)"
        ),
    )
    args = parser.parse_args()

    _require_tools()
    source = _dsn("MIGRATE_SOURCE_DSN")
    target = _dsn("MIGRATE_TARGET_DSN")

    if source == target:
        raise SystemExit("source and target are the same DSN. Refusing to run.")

    print(f"source: {_redact(source)}")
    print(f"target: {_redact(target)}\n")

    source_counts = await _table_counts(source)
    if not source_counts:
        raise SystemExit(f"source has no tables in schema '{SCHEMA}'. Wrong database?")
    target_counts = await _table_counts(target)

    source_total = sum(source_counts.values())
    target_total = sum(target_counts.values())
    print(f"source: {len(source_counts)} tables, {source_total:,} rows")
    print(f"target: {len(target_counts)} tables, {target_total:,} rows")

    # Overwriting a database that already holds data is the one mistake here that
    # cannot be undone, so it takes a second explicit flag.
    if target_total > 0 and not args.allow_nonempty_target:
        raise SystemExit(
            f"\ntarget already holds {target_total:,} rows. If that is the stale "
            "copy you intend to replace, re-run with --allow-nonempty-target."
        )

    skipped = [t for t in TELEMETRY_TABLES if t in source_counts] if args.skip_telemetry else []
    skipped_rows = sum(source_counts[t] for t in skipped)

    print("\nlargest tables to copy:")
    for table, count in sorted(source_counts.items(), key=lambda kv: -kv[1])[:10]:
        marker = "  [structure only]" if table in skipped else ""
        print(f"  {table:<34} {count:,}{marker}")

    if skipped:
        carried = source_total - skipped_rows
        print(
            f"\nskipping rows for {len(skipped)} telemetry table(s): "
            f"{skipped_rows:,} of {source_total:,} rows "
            f"({skipped_rows / source_total:.0%}). Copying {carried:,}."
        )
        print("  structure is still created; only the rows are left behind.")

    if not args.apply:
        print("\nDRY RUN - nothing dumped or written. Re-run with --apply.")
        return 0

    with tempfile.TemporaryDirectory() as workdir:
        dump_path = Path(workdir) / "source.dump"
        print(f"\ndumping schema '{SCHEMA}'...")
        # Custom format so pg_restore can order dependencies itself. --no-owner
        # and --no-acl because roles differ between projects and restoring
        # grants for roles that do not exist aborts the load.
        dump_command = [
            "pg_dump", source,
            "--format=custom", "--no-owner", "--no-acl",
            f"--schema={SCHEMA}",
            f"--file={dump_path}",
        ]
        if args.skip_telemetry:
            # --exclude-table-data, not --exclude-table: the table is still
            # created, so the schema stays complete and nothing needs a second
            # migration pass to become usable.
            for table in skipped:
                dump_command.append(f"--exclude-table-data={SCHEMA}.{table}")
        _run(dump_command)
        print(f"  dump written: {dump_path.stat().st_size / 1e6:.1f} MB")

        print("restoring into target...")
        # pg_restore exits non-zero on benign notices (an extension that already
        # exists, a schema already present), so failures are judged by the row
        # comparison below rather than by the exit code alone.
        restore = subprocess.run(
            ["pg_restore", "--dbname", target, "--no-owner", "--no-acl",
             "--clean", "--if-exists", str(dump_path)],
            capture_output=True, text=True,
        )
        if restore.returncode != 0:
            print(f"  pg_restore reported issues (verifying anyway):\n"
                  f"{restore.stderr[-1500:]}")

    print("\nverifying against the target database, not the restore's exit code:")
    after = await _table_counts(target)
    mismatches: list[str] = []
    for table, source_rows in sorted(source_counts.items()):
        # A deliberately skipped table is expected to arrive empty. Comparing it
        # against the source would report the intended behaviour as data loss and
        # train the reader to ignore this output.
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
        "SUPABASE_DATABASE_URL (pooler, 6543) and SUPABASE_DATABASE_DIRECT_URL "
        "(direct, 5432) in backend/.env to switch."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
