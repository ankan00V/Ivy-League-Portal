#!/usr/bin/env python3
"""Copy the documents the Mongo -> Supabase migration left behind.

The bulk migration succeeded, but a comparison on 2026-08-18 found ~1,313 Mongo
documents with no counterpart in Supabase. This copies the ones worth having.

**What it copies, and what it deliberately does not.**

Real account data is copied. One genuine user never migrated - full name
"ankan ghosh", created 2026-06-03 - together with its profile, 701 interactions,
2 applications, 2 journeys and a post. Its child rows reference it by `user_id`,
so the user row has to land first or the children point at nothing.

Test accounts are skipped: two "Codex Signup" rows and a "Legacy Passwordless"
account on `example.edu`, a reserved test domain. Copying those would put fake
users back into a database that is now the live one.

Derived tables are skipped too, and this matters more than it looks.
`feature_store_rows` (1,142), the three analytics aggregate tables (144) and
`model_drift_reports` (5) are all recomputed from raw interactions, which did
migrate. Copying stale derived rows would reintroduce numbers computed against
a corpus that has since grown from 386 opportunities to over 2,000 - the kind of
silently-wrong metric this repo has published before. Rebuild them instead:

    make warehouse-refresh

Idempotent. Every row upserts on `legacy_mongo_id`, exactly as `migrate_all.py`
does, so a second run converges rather than duplicating.

Dry run unless `--apply` is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
for candidate in (BACKEND_ROOT, REPO_ROOT / "backend" / "migrations" / "neon"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import asyncpg  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.bootstrap import mongo_client_kwargs  # noqa: E402
from app.core.config import settings  # noqa: E402
from migrate_all import _json_safe, coerce, column_types  # noqa: E402

#: Accounts that exist only to exercise the product. `example.edu` is a reserved
#: test domain; "Codex Signup" rows came from an automated signup check.
SKIP_EMAIL_MARKERS = ("@example.edu", "@example.com")
SKIP_NAME_MARKERS = ("codex signup", "legacy passwordless")

#: Recomputed from raw interactions. Copying stale rows would republish metrics
#: derived from a corpus five times smaller than today's.
DERIVED_TABLES = {
    "feature_store_rows",
    "analytics_cohort_aggregates",
    "analytics_daily_aggregates",
    "analytics_funnel_aggregates",
    "model_drift_reports",
}

#: Child collections keyed by `user_id`, copied for recovered users only.
CHILD_COLLECTIONS = (
    "profiles",
    "opportunity_interactions",
    "applications",
    "user_journeys",
    "posts",
    "comments",
    "ask_ai_saved_queries",
    "ask_ai_query_snapshots",
    "rag_feedback_events",
    "experiment_assignments",
)


def is_test_account(doc: dict[str, Any]) -> bool:
    email = str(doc.get("email") or "").strip().lower()
    name = str(doc.get("full_name") or "").strip().lower()
    return any(m in email for m in SKIP_EMAIL_MARKERS) or any(m in name for m in SKIP_NAME_MARKERS)


async def upsert_docs(pg: asyncpg.Connection, table: str, docs: list[dict], *, apply: bool) -> int:
    """Upsert Mongo documents into app.<table>, mirroring migrate_all's mapping."""
    if not docs:
        return 0
    types = await column_types(pg, table)
    if not types:
        return 0
    cols = [c for c in types if c != "id"]
    mapped = set(cols) - {"legacy_mongo_id", "extras"}
    placeholders = ", ".join(
        f"${i+1}::jsonb" if types[c] == "jsonb" else f"${i+1}" for i, c in enumerate(cols)
    )
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "legacy_mongo_id")
    sql = (
        f'INSERT INTO app.{table} ({", ".join(chr(34)+c+chr(34) for c in cols)}) '
        f"VALUES ({placeholders}) ON CONFLICT (legacy_mongo_id) DO UPDATE SET {updates}"
    )

    rows = []
    for doc in docs:
        leftover = {k: v for k, v in doc.items() if k != "_id" and k not in mapped}
        row = []
        for c in cols:
            if c == "legacy_mongo_id":
                row.append(str(doc.get("_id")))
            elif c == "extras":
                row.append(json.dumps(_json_safe(leftover)))
            else:
                row.append(coerce(doc.get(c), types[c]))
        rows.append(tuple(row))

    if apply:
        await pg.executemany(sql, rows)
    return len(rows)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write. Default is a dry run.")
    args = parser.parse_args()

    kw = dict(mongo_client_kwargs())
    kw["serverSelectionTimeoutMS"] = 25000
    mongo = AsyncIOMotorClient(settings.MONGODB_URL, **kw)
    pg = await asyncpg.connect(settings.SUPABASE_DATABASE_URL, timeout=60, statement_cache_size=0)

    report: dict[str, Any] = {"mode": "apply" if args.apply else "dry-run", "users": {}, "children": {}}
    try:
        db = mongo[settings.MONGODB_DB_NAME]

        existing = {
            str(r["email"]).strip('"').lower()
            for r in await pg.fetch('SELECT email FROM app."users"')
        }

        recover: list[dict] = []
        skipped: list[str] = []
        async for doc in db["users"].find({}):
            email = str(doc.get("email") or "").strip().lower()
            if email in existing:
                continue
            if is_test_account(doc):
                skipped.append(email)
                continue
            recover.append(doc)

        report["users"]["recoverable"] = [str(d.get("email")) for d in recover]
        report["users"]["skipped_as_test"] = skipped
        report["users"]["copied"] = await upsert_docs(pg, "users", recover, apply=args.apply)

        # Children only for the users we just recovered, so nothing unrelated moves.
        user_ids = [d["_id"] for d in recover]
        if user_ids:
            for coll in CHILD_COLLECTIONS:
                if coll in DERIVED_TABLES:
                    continue
                docs = await db[coll].find({"user_id": {"$in": user_ids}}).to_list(length=None)
                if docs:
                    report["children"][coll] = await upsert_docs(pg, coll, docs, apply=args.apply)

        report["derived_tables_skipped"] = sorted(DERIVED_TABLES)
        report["rebuild_derived_with"] = "make warehouse-refresh"

        print(json.dumps(report, indent=2, default=str))
        if not args.apply:
            print("\nDry run. Re-run with --apply to write these rows.", file=sys.stderr)
        return 0
    finally:
        await pg.close()
        mongo.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
