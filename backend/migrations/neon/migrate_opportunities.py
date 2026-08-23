"""Copy opportunities from MongoDB Atlas into Neon.

Idempotent by design: every row upserts on `url`, which is the same natural key
the scrapers already dedupe on, so the script can be re-run while Mongo is still
taking writes and the two converge rather than duplicating.

Fields the application filters, sorts or joins on become real columns. Everything
else is folded into `extras` untouched, so nothing is dropped on the way across
and a field we did not anticipate is still recoverable afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[2]
ENV = dotenv_values(BACKEND / ".env")

# Columns that exist in app.opportunities, in insert order.
COLUMNS = [
    "legacy_mongo_id", "url", "canonical_url_hash", "canonical_key",
    "title_company_location_hash", "duplicate_cluster_key",
    "title", "description", "normalized_title", "normalized_organization",
    "university", "location", "work_mode", "stipend", "eligibility",
    "ppo_available",
    "opportunity_type", "domain", "portal_category", "source", "source_id",
    "opportunity_status", "lifecycle_status", "trust_status",
    "url_liveness_status", "is_employer_post", "quality_review_required",
    "trust_score", "risk_score", "quality_score", "freshness_score",
    "dedup_score", "source_count", "duplicate_count",
    "stipend_min", "stipend_max", "stipend_currency", "stipend_period",
    "duration_months",
    "tags", "seen_on", "batch_years",
    "embedding", "embedding_text_hash", "embedding_model_version",
    "embedding_updated_at",
    "deadline", "duration_start", "duration_end", "published_at", "paused_at",
    "closed_at", "reviewed_at", "url_last_checked_at", "last_quality_run_at",
    "lifecycle_updated_at", "created_at", "updated_at", "last_seen_at",
    "extras",
]
# Anything not mapped to a column lands in extras rather than being discarded.
MAPPED = set(COLUMNS) - {"legacy_mongo_id", "extras"}


def target_dsn() -> str:
    """Connection string for the migration target.

    Supabase first, Neon second: Neon has no India region and measured 130ms per
    query from Singapore against 44ms here, so Supabase took over as the target.
    The Neon entries stay in .env, commented, so that project remains usable.
    """
    dsn = ENV.get("SUPABASE_DATABASE_DIRECT_URL") or ENV.get("NEON_DATABASE_DIRECT_URL")
    if not dsn:
        raise SystemExit("no SUPABASE_DATABASE_DIRECT_URL or NEON_DATABASE_DIRECT_URL in .env")
    return dsn.replace("?sslmode=require", "")

def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        # Mongo stores naive UTC; Postgres timestamptz wants it explicit.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _num(value: Any, cast, lo=None, hi=None):
    try:
        out = cast(value)
    except (TypeError, ValueError):
        return None
    if lo is not None and out < lo:
        return lo
    if hi is not None and out > hi:
        return hi
    return out


def _vector(value: Any) -> str | None:
    """pgvector accepts its literal text form: '[1,2,3]'."""
    if not isinstance(value, list) or not value:
        return None
    # 384 = all-MiniLM-L6-v2, the model actually in use. A vector of any
    # other width is from an older scheme and is not comparable, so it is
    # dropped rather than silently mixed into the index.
    if len(value) != 384:
        return None
    try:
        return "[" + ",".join(f"{float(x):.6f}" for x in value) + "]"
    except (TypeError, ValueError):
        return None


def to_row(doc: dict[str, Any]) -> tuple | None:
    url = str(doc.get("url") or "").strip()
    title = str(doc.get("title") or "").strip()
    if not url or not title:
        return None  # unusable without a key and a name

    extras = {
        k: v for k, v in doc.items()
        if k not in MAPPED and k != "_id"
    }
    # Keep it JSON-clean: ObjectId and datetime are not JSON types.
    extras = json.loads(json.dumps(extras, default=str))

    return (
        str(doc.get("_id")),
        url,
        doc.get("canonical_url_hash"),
        doc.get("canonical_key"),
        doc.get("title_company_location_hash"),
        doc.get("duplicate_cluster_key"),
        title[:2000],
        str(doc.get("description") or ""),
        doc.get("normalized_title"),
        doc.get("normalized_organization"),
        doc.get("university"),
        doc.get("location"),
        doc.get("work_mode"),
        doc.get("stipend"),
        doc.get("eligibility"),
        doc.get("ppo_available"),
        doc.get("opportunity_type"),
        doc.get("domain"),
        doc.get("portal_category"),
        doc.get("source"),
        doc.get("source_id"),
        str(doc.get("opportunity_status") or "active"),
        str(doc.get("lifecycle_status") or "published"),
        str(doc.get("trust_status") or "unreviewed"),
        str(doc.get("url_liveness_status") or "unknown"),
        bool(doc.get("is_employer_post") or False),
        bool(doc.get("quality_review_required") or False),
        _num(doc.get("trust_score"), int, 0, 100) or 50,
        _num(doc.get("risk_score"), int, 0, 100) or 50,
        _num(doc.get("quality_score"), float, 0.0, 100.0),
        _num(doc.get("freshness_score"), float, 0.0, 1.0) or 1.0,
        _num(doc.get("dedup_score"), float, 0.0, 1.0) or 0.0,
        _num(doc.get("source_count"), int, 1) or 1,
        _num(doc.get("duplicate_count"), int, 0) or 0,
        _num(doc.get("stipend_min"), int, 0),
        _num(doc.get("stipend_max"), int, 0),
        doc.get("stipend_currency"),
        doc.get("stipend_period"),
        _num(doc.get("duration_months"), float, 0.0),
        [str(x) for x in (doc.get("tags") or []) if x],
        [str(x) for x in (doc.get("seen_on") or []) if x],
        [int(x) for x in (doc.get("batch_years") or []) if isinstance(x, (int, float))],
        _vector(doc.get("embedding")),
        doc.get("embedding_text_hash"),
        doc.get("embedding_model_version"),
        _dt(doc.get("embedding_updated_at")),
        _dt(doc.get("deadline")),
        _dt(doc.get("duration_start")),
        _dt(doc.get("duration_end")),
        _dt(doc.get("published_at")),
        _dt(doc.get("paused_at")),
        _dt(doc.get("closed_at")),
        _dt(doc.get("reviewed_at")),
        _dt(doc.get("url_last_checked_at")),
        _dt(doc.get("last_quality_run_at")),
        _dt(doc.get("lifecycle_updated_at")) or datetime.now(timezone.utc),
        _dt(doc.get("created_at")) or datetime.now(timezone.utc),
        _dt(doc.get("updated_at")) or datetime.now(timezone.utc),
        _dt(doc.get("last_seen_at")) or datetime.now(timezone.utc),
        json.dumps(extras),
    )


def upsert_sql() -> str:
    cols = ", ".join(COLUMNS)
    params = ", ".join(
        # embedding and extras need an explicit cast from their text form
        f"${i+1}::vector" if c == "embedding" else (f"${i+1}::jsonb" if c == "extras" else f"${i+1}")
        for i, c in enumerate(COLUMNS)
    )
    # legacy_mongo_id is excluded as well as url. Two Mongo documents can share
    # a URL - the corpus has such pairs - and on the url-conflict path this tried
    # to overwrite the stored id with the incoming one, colliding with the unique
    # constraint on a different row. The row already has an identity; the first
    # one to arrive keeps it.
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("url", "legacy_mongo_id")
    )
    return (
        f"INSERT INTO app.opportunities ({cols}) VALUES ({params}) "
        f"ON CONFLICT (url) DO UPDATE SET {updates}"
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()

    mongo = AsyncIOMotorClient(ENV["MONGODB_URL"], serverSelectionTimeoutMS=30000,
                               socketTimeoutMS=180000)
    col = mongo[ENV.get("MONGODB_DB_NAME", "vidyaverse")]["opportunities"]
    total = await col.count_documents({})
    print(f"  Mongo documents: {total}", flush=True)

    # statement_cache_size=0: Supabase fronts Postgres with pgbouncer, which
    # does not support the prepared statements asyncpg caches by default.
    pg = await asyncpg.connect(target_dsn(), ssl="require", timeout=60,
                               statement_cache_size=0)
    sql = upsert_sql()

    cursor = col.find({})
    if args.limit:
        cursor = cursor.limit(args.limit)

    batch: list[tuple] = []
    migrated = skipped = 0
    async for doc in cursor:
        row = to_row(doc)
        if row is None:
            skipped += 1
            continue
        batch.append(row)
        if len(batch) >= args.batch:
            await pg.executemany(sql, batch)
            migrated += len(batch)
            print(f"    migrated {migrated}", flush=True)
            batch = []
    if batch:
        await pg.executemany(sql, batch)
        migrated += len(batch)

    count = await pg.fetchval("SELECT count(*) FROM app.opportunities")
    with_vec = await pg.fetchval("SELECT count(*) FROM app.opportunities WHERE embedding IS NOT NULL")
    active = await pg.fetchval("SELECT count(*) FROM app.opportunities WHERE opportunity_status <> 'removed'")
    print(f"\n  migrated={migrated} skipped={skipped}")
    print(f"  neon rows={count}  active={active}  with embedding={with_vec}")
    await pg.close()
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
