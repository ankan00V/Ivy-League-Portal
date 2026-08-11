"""Reads opportunities from Postgres (Supabase) instead of MongoDB.

Built because Atlas M0 stopped being able to answer the feed at all: the query
timed out after 60 seconds and returned 500, which is what a throttled shared
cluster does when asked for a few thousand documents. The same corpus lives in
Supabase in Mumbai at roughly 44ms.

Two decisions worth stating.

It returns real `Opportunity` instances rather than dicts or rows. Everything
downstream - is_student_visible_opportunity, _feed_priority, the diversity rule,
the response serialisers - already works on that type, so reconstructing the
model keeps the swap invisible to the rest of the endpoint and avoids a parallel
set of shapes that would drift.

It filters and orders in SQL rather than in Python. The Mongo path pulled a
window of ten times the requested limit and discarded most of it in memory; at a
2000-row request that is 20,000 documents fetched to serve 2,000. Postgres has
indexes for exactly this, so status, portal and ordering are pushed down and the
window shrinks to what is actually needed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

# Columns mapped straight back onto the model. Anything else lives in `extras`
# and is merged in below, so a field added to the model later still arrives.
_SELECT = """
    legacy_mongo_id, url, title, description, normalized_title,
    normalized_organization, university, location, work_mode, stipend,
    eligibility, ppo_available, opportunity_type, domain, portal_category,
    source, source_id, opportunity_status, lifecycle_status, trust_status,
    url_liveness_status, is_employer_post, quality_review_required,
    trust_score, risk_score, quality_score, freshness_score, dedup_score,
    source_count, duplicate_count, stipend_min, stipend_max, stipend_currency,
    stipend_period, duration_months, tags, seen_on, batch_years,
    embedding_text_hash, embedding_model_version, embedding_updated_at,
    canonical_url_hash, canonical_key, title_company_location_hash,
    duplicate_cluster_key, deadline, duration_start, duration_end,
    published_at, paused_at, closed_at, reviewed_at, url_last_checked_at,
    last_quality_run_at, lifecycle_updated_at, created_at, updated_at,
    last_seen_at, extras
"""


async def get_pool() -> asyncpg.Pool:
    """Shared connection pool.

    statement_cache_size=0 because Supabase fronts Postgres with pgbouncer,
    which does not support the prepared statements asyncpg caches by default.
    """
    global _pool
    if _pool is None or _pool._closed:  # type: ignore[attr-defined]
        dsn = settings.SUPABASE_DATABASE_URL or settings.NEON_DATABASE_URL
        if not dsn:
            raise RuntimeError("no Postgres URL configured")
        _pool = await asyncpg.create_pool(
            dsn.replace("?sslmode=require", ""),
            ssl="require",
            # Opened eagerly and never grown: a new connection needs a DNS
            # lookup, and during a scrape that lookup fails outright.
            min_size=max(4, int(settings.NEON_POOL_MAX_SIZE)),
            max_size=max(4, int(settings.NEON_POOL_MAX_SIZE)),
            command_timeout=float(settings.NEON_COMMAND_TIMEOUT_SECONDS),
            statement_cache_size=0,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None and not _pool._closed:  # type: ignore[attr-defined]
        await _pool.close()
    _pool = None


def _to_model(record: asyncpg.Record):
    """Rebuild an Opportunity from a row.

    `extras` is merged first so real columns always win: the column is the
    migrated, corrected value, while extras is whatever the source document
    happened to carry.
    """
    from beanie import PydanticObjectId

    from app.models.opportunity import Opportunity

    data: dict[str, Any] = {}
    raw_extras = record.get("extras")
    if raw_extras:
        try:
            parsed = json.loads(raw_extras) if isinstance(raw_extras, str) else raw_extras
            if isinstance(parsed, dict):
                data.update(parsed)
        except (ValueError, TypeError):
            pass

    for key, value in record.items():
        if key in ("extras", "legacy_mongo_id") or value is None:
            continue
        data[key] = list(value) if isinstance(value, (list, tuple)) else value

    known = set(Opportunity.model_fields)
    payload = {k: v for k, v in data.items() if k in known}
    payload.setdefault("title", "")
    payload.setdefault("description", "")
    payload.setdefault("url", "")

    model = Opportunity.model_construct(**payload)
    # Preserve identity so saved/applied lookups keyed on the old id still work.
    legacy = record.get("legacy_mongo_id")
    if legacy:
        try:
            model.id = PydanticObjectId(legacy)
        except Exception:
            model.id = None
    return model


async def load_active_opportunities(
    *,
    domain: str | None = None,
    portal: str | None = None,
    limit: int = 100,
    window_multiplier: int = 3,
) -> list:
    """Active rows for the feed, newest first.

    The window is a small multiple of the limit rather than ten times it: the
    Python-side filters still drop some rows, but status and portal are already
    applied here, so far less is fetched only to be discarded.
    """
    pool = await get_pool()
    clauses = ["opportunity_status <> 'removed'"]
    params: list[Any] = []

    if domain:
        params.append(domain)
        clauses.append(f"domain = ${len(params)}")
    normalized_portal = str(portal or "").strip().lower()
    if normalized_portal in {"career", "competitive", "other"}:
        params.append(normalized_portal)
        clauses.append(f"portal_category = ${len(params)}")

    params.append(max(1, limit) * max(1, window_multiplier))
    sql = (
        f"SELECT {_SELECT} FROM app.opportunities "
        f"WHERE {' AND '.join(clauses)} "
        f"ORDER BY last_seen_at DESC NULLS LAST, created_at DESC "
        f"LIMIT ${len(params)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_to_model(r) for r in rows]


async def count_active() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT count(*) FROM app.opportunities WHERE opportunity_status <> 'removed'"
        ) or 0)


async def health() -> dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT count(*) FROM app.opportunities")
        return {"ok": True, "rows": int(total or 0)}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:160]}

# Columns written when mirroring a scraped row. `embedding` is deliberately
# absent: the embedding pipeline owns it and writes on its own schedule, so
# copying a stale or empty vector here would overwrite a good one.
_WRITE_COLUMNS = [
    "legacy_mongo_id", "url", "title", "description", "normalized_title",
    "normalized_organization", "university", "location", "work_mode", "stipend",
    "eligibility", "ppo_available", "opportunity_type", "domain",
    "portal_category", "source", "source_id", "opportunity_status",
    "lifecycle_status", "trust_status", "url_liveness_status",
    "is_employer_post", "quality_review_required", "trust_score", "risk_score",
    "quality_score", "freshness_score", "dedup_score", "source_count",
    "duplicate_count", "stipend_min", "stipend_max", "stipend_currency",
    "stipend_period", "duration_months", "tags", "seen_on", "batch_years",
    "canonical_url_hash", "canonical_key", "title_company_location_hash",
    "duplicate_cluster_key", "deadline", "published_at", "created_at",
    "updated_at", "last_seen_at",
]

_NUMERIC = {"trust_score", "risk_score", "source_count", "duplicate_count",
            "stipend_min", "stipend_max"}
_FLOATS = {"quality_score", "freshness_score", "dedup_score", "duration_months"}
_BOOLS = {"is_employer_post", "quality_review_required"}
_ARRAYS = {"tags": str, "seen_on": str, "batch_years": int}


def _write_value(model, column: str):
    from datetime import timezone

    value = getattr(model, column, None)
    if column == "legacy_mongo_id":
        raw = getattr(model, "id", None)
        return str(raw) if raw else None
    if value is None:
        return None
    if column in _ARRAYS:
        cast = _ARRAYS[column]
        return [cast(x) for x in value] if isinstance(value, (list, tuple)) else None
    if column in _BOOLS:
        return bool(value)
    if column in _NUMERIC:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if column in _FLOATS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if hasattr(value, "tzinfo"):
        # Mongo stores naive UTC; timestamptz needs the zone stated.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return value
    return str(value)


async def upsert_opportunities(models: list) -> int:
    """Mirror scraped rows into Postgres.

    The scraper still writes to Mongo first, because its dedup relies on Beanie
    documents and a rewrite of that logic would risk the correctness of the
    thing that stops duplicate postings reaching students. Mirroring afterwards
    makes Postgres current without touching any of it, and once writes move over
    fully this becomes the write path rather than a copy of it.

    Conflicts resolve on `url`, the same natural key Mongo dedupes on, so a
    re-scrape of an unchanged posting updates rather than duplicates.
    """
    if not models:
        return 0
    pool = await get_pool()
    cols = ", ".join(_WRITE_COLUMNS)
    params = ", ".join(f"${i+1}" for i in range(len(_WRITE_COLUMNS)))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _WRITE_COLUMNS
        if c not in ("url", "legacy_mongo_id", "created_at")
    )
    sql = (
        f"INSERT INTO app.opportunities ({cols}) VALUES ({params}) "
        f"ON CONFLICT (url) DO UPDATE SET {updates}"
    )
    rows = []
    for model in models:
        url = str(getattr(model, "url", "") or "").strip()
        if not url:
            continue
        rows.append(tuple(_write_value(model, c) for c in _WRITE_COLUMNS))
    if not rows:
        return 0
    async with pool.acquire() as conn:
        # A mirror failure must never fail the scrape that produced the data.
        try:
            await conn.executemany(sql, rows)
        except Exception:
            logger.exception("postgres mirror failed for %d rows", len(rows))
            return 0
    return len(rows)
