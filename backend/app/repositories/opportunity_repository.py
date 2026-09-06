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

from app.core.config import settings, resolve_postgres_dsn, postgres_connect_args

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
        dsn = resolve_postgres_dsn()
        if not dsn:
            raise RuntimeError("no Postgres URL configured")
        connect_dsn, ssl_mode = postgres_connect_args(dsn)
        _pool = await asyncpg.create_pool(
            connect_dsn,
            ssl=ssl_mode,
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


#: The visibility rule, as SQL.
#:
#: Every other read path funnels through `is_student_visible_opportunity`, which
#: additionally requires a published lifecycle, a deadline that has not passed,
#: and a trust verdict that is not blocking. The paged feed - the primary public
#: one - had only `opportunity_status = 'active'` and applied no Python filter to
#: the rows it returned, so it was one row away from serving a listing the trust
#: system had flagged.
#:
#: Measured on the live corpus when this was written: 0 of 2,242 active rows fell
#: foul of any of the four predicates, so nothing was leaking that day. That is a
#: statement about today's data, not about the query, and it is exactly the kind
#: of gap that is discovered by the first row that trips it.
#:
#: NULLs are treated the way `ensure_opportunity_trust` treats a missing
#: assessment - as unreviewed and visible - so scraped rows that predate trust
#: scoring keep behaving as they do everywhere else.
STUDENT_VISIBILITY_CLAUSES: tuple[str, ...] = (
    "coalesce(lifecycle_status, 'published') = 'published'",
    "(deadline IS NULL OR deadline >= now())",
    "coalesce(trust_status, 'unreviewed') IN ('verified', 'unreviewed')",
    "coalesce(risk_score, 0) < 75",
)


async def load_opportunity_page(
    *,
    portal: str | None = None,
    domain: str | None = None,
    role_track: str | None = None,
    placement: str | None = None,
    specialities: list[str] | None = None,
    page: int = 1,
    per_page: int = 12,
) -> tuple[list, int]:
    """One page of the feed, filtered and counted in SQL. Returns (rows, total).

    The feed used to fetch every active listing and filter in the browser, which
    moved 3.36 MB out of Postgres per request and exhausted a 5.5 GB monthly
    egress allowance in roughly 1,600 page loads. Filtering here is only possible
    because role_track and feed_categories are stored columns now - as computed
    properties they could not appear in a WHERE clause, so the corpus had to be
    loaded before anything could be excluded.

    `total` is the count of rows matching the filter, not the page size. The
    pager needs it to render page numbers, and it is a second query rather than
    a window function because COUNT(*) over the same indexed predicate is cheap
    and keeps the row query's plan simple.
    """
    pool = await get_pool()
    clauses = ["opportunity_status = 'active'", *STUDENT_VISIBILITY_CLAUSES]
    params: list[Any] = []

    if domain:
        params.append(domain)
        clauses.append(f"domain = ${len(params)}")

    normalized_portal = str(portal or "").strip().lower()
    if normalized_portal in {"career", "competitive", "other"}:
        params.append(normalized_portal)
        clauses.append(f"portal_category = ${len(params)}")

    normalized_track = str(role_track or "").strip().lower()
    if normalized_track in {"technical", "non_technical"}:
        params.append(normalized_track)
        clauses.append(f"role_track = ${len(params)}")

    normalized_placement = str(placement or "").strip().lower()
    if normalized_placement in {"india", "remote", "hybrid", "international"}:
        params.append(normalized_placement)
        # Array containment, so a remote role in Bengaluru still matches both
        # india and remote rather than being forced into one bucket.
        clauses.append(f"feed_categories @> ARRAY[${len(params)}]::text[]")

    keywords = [k.strip().lower() for k in (specialities or []) if k and k.strip()]
    if keywords:
        # OR across selections: picking Software and Data & AI widens the list.
        # Matched against title only. The speciality chips were matched against
        # descriptions client-side, and reintroducing that here would mean a
        # sequential scan of every body on every page request - the cost this
        # change exists to remove.
        ors = []
        for keyword in keywords:
            params.append(f"%{keyword}%")
            ors.append(f"lower(title) LIKE ${len(params)}")
        clauses.append("(" + " OR ".join(ors) + ")")

    where = " AND ".join(clauses)
    safe_per_page = max(1, min(int(per_page), 100))
    offset = max(0, (max(1, int(page)) - 1) * safe_per_page)

    async with pool.acquire() as conn:
        total = int(await conn.fetchval(
            f"SELECT count(*) FROM app.opportunities WHERE {where}", *params
        ) or 0)
        params.extend([safe_per_page, offset])
        rows = await conn.fetch(
            f"SELECT {_SELECT} FROM app.opportunities WHERE {where} "
            f"ORDER BY last_seen_at DESC NULLS LAST, created_at DESC "
            f"LIMIT ${len(params)-1} OFFSET ${len(params)}",
            *params,
        )
    return [_to_model(r) for r in rows], total


async def feed_facet_counts(
    *, portal: str | None = None, role_track: str | None = None
) -> dict[str, Any]:
    """Counts for the filter controls, aggregated in SQL.

    The tab and pill counts were derived by classifying the whole corpus in the
    browser, which is the other half of why every listing was downloaded. Two
    GROUP BY queries return the same numbers in a few hundred bytes.

    Placement counts respect the selected role track but not the placement pill
    itself, so each pill shows how many listings it would yield rather than how
    many are showing now.
    """
    pool = await get_pool()
    clauses = ["opportunity_status = 'active'", *STUDENT_VISIBILITY_CLAUSES]
    params: list[Any] = []

    normalized_portal = str(portal or "").strip().lower()
    if normalized_portal in {"career", "competitive", "other"}:
        params.append(normalized_portal)
        clauses.append(f"portal_category = ${len(params)}")
    where = " AND ".join(clauses)

    track_params = list(params)
    track_clauses = list(clauses)
    normalized_track = str(role_track or "").strip().lower()
    if normalized_track in {"technical", "non_technical"}:
        track_params.append(normalized_track)
        track_clauses.append(f"role_track = ${len(track_params)}")
    track_where = " AND ".join(track_clauses)

    async with pool.acquire() as conn:
        track_rows = await conn.fetch(
            f"SELECT role_track, count(*) AS n FROM app.opportunities WHERE {where} GROUP BY 1",
            *params,
        )
        placement_rows = await conn.fetch(
            f"SELECT unnest(feed_categories) AS cat, count(*) AS n "
            f"FROM app.opportunities WHERE {track_where} GROUP BY 1",
            *track_params,
        )
        track_total = int(await conn.fetchval(
            f"SELECT count(*) FROM app.opportunities WHERE {track_where}", *track_params
        ) or 0)

    tracks = {str(r["role_track"] or "unknown"): int(r["n"]) for r in track_rows}
    placements = {str(r["cat"]): int(r["n"]) for r in placement_rows}
    return {
        "tracks": {
            "all": sum(tracks.values()),
            "technical": tracks.get("technical", 0),
            "non_technical": tracks.get("non_technical", 0),
        },
        "placements": {
            "all": track_total,
            "india": placements.get("india", 0),
            "remote": placements.get("remote", 0),
            "hybrid": placements.get("hybrid", 0),
            "international": placements.get("international", 0),
        },
    }


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
    # Facets, written here so the feed can filter and count in SQL instead of
    # loading the corpus into the browser. Omitting them from this list is not a
    # missing optimisation - it silently reverts the backfill, because every
    # INSERT leaves the columns NULL and the scraper re-inserts constantly.
    "role_track", "feed_categories",
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
    # Derived at write time from the same classifiers the API used to run per
    # request. The scraped model carries no such attribute, so these are
    # computed rather than read.
    if column == "role_track":
        from app.services.role_classification import classify_role_track

        return classify_role_track(
            title=getattr(model, "title", None),
            description=getattr(model, "description", None),
            tags=getattr(model, "tags", None),
            opportunity_type=getattr(model, "opportunity_type", None),
        )
    if column == "portal_category":
        # Persisted rather than derived per request. resolve_opportunity_portal
        # falls back to the type/title/description when the column is NULL, and
        # 946 active rows relied on that fallback - so a SQL filter on the raw
        # column silently dropped every one of them from the career feed.
        from app.services.opportunity_visibility import resolve_opportunity_portal

        return resolve_opportunity_portal(
            opportunity_type=getattr(model, "opportunity_type", None),
            title=getattr(model, "title", None),
            description=getattr(model, "description", None),
            portal_category=value,
        )
    if column == "feed_categories":
        from app.services.opportunity_placement import classify_placement

        return list(
            classify_placement(
                location=getattr(model, "location", None),
                work_mode=getattr(model, "work_mode", None),
                title=getattr(model, "title", None),
                description=getattr(model, "description", None),
                source=getattr(model, "source", None),
            )
            or []
        )
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
