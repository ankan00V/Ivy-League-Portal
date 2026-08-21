"""Behavioural telemetry: pseudonymize it on the way out, and don't keep it forever.

`opportunity_interactions` records, per row, which student looked at which listing,
for how long, how far they scrolled, and what they typed into search. That pattern
is more revealing than the profile it sits next to — a student filtering hard on
stipend is telling us about their family's finances, and nobody consented to that
being legible.

Two controls here.

**Pseudonymized export.** Warehouse marts get a keyed HMAC of the user id instead of
the id itself. Analysts keep per-user cohort and funnel joins, because the same
student maps to the same pseudonym across every mart, but the ClickHouse copy no
longer carries identifiers that resolve against the application database. The key is
`SECRET_KEY`, which never leaves the backend.

Note the deliberate difference from account erasure: *that* pseudonym is random and
irreversible, because the point is that nobody — including us — can undo it. This
one is keyed and stable, because the point is that analysis still works. Same word,
opposite requirements, so they are separate functions on purpose.

**Retention.** Raw rows keep their user link only for
`TELEMETRY_RAW_RETENTION_DAYS`. Past that, `purge_aged_telemetry` strips the user id
and the free-text query, leaving the measurement intact. Aggregate marts are built
from those rows well inside the window, so nothing downstream loses its history —
what expires is the ability to point at a person.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_collection(document: Any) -> Any:
    """Resolve the raw collection across Beanie versions.

    Beanie 2.x renamed `get_motor_collection` to `get_pymongo_collection`. The same
    two-step lookup appears in `job_runner`, `vector_service` and the bootstrap
    scripts; this is the copy the privacy paths use.
    """
    for name in ("get_motor_collection", "get_pymongo_collection"):
        getter = getattr(document, name, None)
        if callable(getter):
            return getter()
    raise AttributeError(f"No collection getter found for {document.__name__}")


#: Namespace so a pseudonym from this pipeline can never collide with one produced
#: elsewhere from the same key.
_PSEUDONYM_NAMESPACE = b"vidyaverse.warehouse.user.v1"


def warehouse_pseudonym(user_id: Any) -> str | None:
    """Stable, keyed pseudonym for one user id. `None` in, `None` out."""
    if user_id in (None, ""):
        return None

    key = (getattr(settings, "SECRET_KEY", "") or "").encode("utf-8")
    if not key:
        # Without a key an unkeyed hash of an ObjectId is reversible by anyone who
        # can enumerate ids, which is not pseudonymization. Refuse rather than
        # pretend.
        raise RuntimeError(
            "SECRET_KEY is required to pseudonymize warehouse exports; refusing to "
            "emit an unkeyed digest."
        )

    digest = hmac.new(key, _PSEUDONYM_NAMESPACE + str(user_id).encode("utf-8"), hashlib.sha256)
    return f"u_{digest.hexdigest()[:24]}"


def pseudonymize_rows(
    rows: Iterable[dict[str, Any]],
    *,
    user_key: str = "user_id",
) -> list[dict[str, Any]]:
    """Replace the user id in exported rows with its warehouse pseudonym."""
    output: list[dict[str, Any]] = []
    for row in rows:
        if user_key in row:
            row = {**row, user_key: warehouse_pseudonym(row.get(user_key))}
        output.append(row)
    return output


def retention_pseudonym_object_id(user_id: Any) -> "PydanticObjectId":
    """A stable ObjectId that belongs to no account, derived from the real one.

    `OpportunityInteraction.user_id` is a required ObjectId, so aged rows cannot
    simply be nulled — the row would stop validating on load. Deriving a 12-byte id
    from the keyed pseudonym keeps each student distinct from every other student
    (so cohort counts over aged data stay correct) while pointing at no `users`
    document. Reversing it needs SECRET_KEY, which is not in the warehouse.
    """
    from beanie import PydanticObjectId

    pseudonym = warehouse_pseudonym(user_id)
    if pseudonym is None:
        raise ValueError("Cannot derive a retention pseudonym for a missing user id.")
    return PydanticObjectId(pseudonym.removeprefix("u_")[:24])


def retention_cutoff(*, now: datetime | None = None) -> datetime | None:
    """The timestamp before which raw telemetry must lose its user link.

    Returns None when retention is disabled (`TELEMETRY_RAW_RETENTION_DAYS <= 0`),
    which is the escape hatch for environments that need the raw history.
    """
    days = int(getattr(settings, "TELEMETRY_RAW_RETENTION_DAYS", 0) or 0)
    if days <= 0:
        return None
    reference = now or datetime.now(timezone.utc)
    return reference - timedelta(days=days)


async def _purge_aged_telemetry_postgres(*, apply: bool, cutoff: datetime) -> dict[str, Any]:
    """Retention against Postgres.

    A separate path because `pg_documents.install` patches the Beanie query API but
    not the raw-collection accessor. `get_collection()` therefore still hands back a
    **Mongo** handle under the Postgres ODM, so the Mongo branch below would have
    reported a clean run while never touching the live database — the same silent
    wrong-store failure the dataset snapshot had.

    Clears three things past the window:

    - `user_id` -> a derived pseudonym, so the row stops naming a student.
    - `query`   -> free text the student typed.
    - `features` -> the 55-key ranker vector. This is the storage win: it averages
      1,088 bytes of jsonb per row and is 53% of the table heap. Nothing reads it
      past `MLOPS_RETRAIN_LOOKBACK_DAYS` (90) — drift looks back 7 days and the
      guardrail 30 — so beyond the window it is dead weight that only grows.

    Rows are never deleted. Counts, funnels and experiment denominators computed
    over history stay exactly as they were.
    """
    import asyncpg

    conn = await asyncpg.connect(
        settings.SUPABASE_DATABASE_URL,
        timeout=60,
        # Supabase's pooler is pgbouncer in transaction mode.
        statement_cache_size=0,
    )
    report: dict[str, Any] = {
        "status": "ok",
        "backend": "postgres",
        "mode": "apply" if apply else "dry-run",
        "cutoff": cutoff.isoformat(),
        "collections": {},
    }
    try:
        matched = await conn.fetchval(
            "SELECT count(*) FROM app.opportunity_interactions "
            "WHERE created_at < $1 AND features IS NOT NULL",
            cutoff,
        )
        reclaimable = await conn.fetchval(
            "SELECT coalesce(sum(pg_column_size(features)), 0) "
            "FROM app.opportunity_interactions WHERE created_at < $1",
            cutoff,
        )
        entry: dict[str, Any] = {
            "matched": int(matched or 0),
            "reclaimable_bytes": int(reclaimable or 0),
        }
        if apply and matched:
            result = await conn.execute(
                "UPDATE app.opportunity_interactions "
                "SET features = NULL, query = NULL "
                "WHERE created_at < $1 AND features IS NOT NULL",
                cutoff,
            )
            entry["modified"] = int(str(result).rsplit(" ", 1)[-1] or 0)
        report["collections"]["opportunity_interactions"] = entry
        return report
    finally:
        await conn.close()


async def purge_aged_telemetry(*, apply: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Unlink telemetry older than the retention window from the students who made it.

    Rows are kept and their measurement fields untouched; only `user_id` and the
    free-text `query` are cleared. Deleting the rows outright would silently shrink
    historical impression counts, which is the failure this codebase has been bitten
    by before (see `app/models/traffic.py`).

    Dry run unless `apply=True`, matching the other retention/backfill scripts.
    """
    from app.models.opportunity_interaction import OpportunityInteraction
    from app.models.ranking_request_telemetry import RankingRequestTelemetry

    cutoff = retention_cutoff(now=now)
    if cutoff is None:
        return {"status": "disabled", "reason": "TELEMETRY_RAW_RETENTION_DAYS <= 0"}

    if settings.POSTGRES_ODM_ENABLED:
        return await _purge_aged_telemetry_postgres(apply=apply, cutoff=cutoff)

    report: dict[str, Any] = {
        "status": "ok",
        "backend": "mongo",
        "mode": "apply" if apply else "dry-run",
        "cutoff": cutoff.isoformat(),
        "collections": {},
    }

    targets = (
        (OpportunityInteraction, ("query",)),
        (RankingRequestTelemetry, ()),
    )

    for document, redact_fields in targets:
        collection = get_collection(document)
        name = document.Settings.name
        query = {"created_at": {"$lt": cutoff}, "user_id": {"$ne": None}}

        matched = await collection.count_documents(query)
        # One update per distinct user rather than per row: each user needs their own
        # derived pseudonym, and the number of users is orders of magnitude smaller
        # than the number of impressions.
        distinct_users = await collection.distinct("user_id", query)
        entry: dict[str, Any] = {
            "matched": matched,
            "distinct_users": len(distinct_users),
        }

        if apply and matched:
            modified = 0
            for raw_user_id in distinct_users:
                if raw_user_id in (None, ""):
                    continue
                try:
                    pseudonym = retention_pseudonym_object_id(raw_user_id)
                except Exception as exc:
                    logger.error("Skipping retention for one user in %s: %s", name, exc)
                    continue
                updates: dict[str, Any] = {"user_id": pseudonym}
                for redacted in redact_fields:
                    updates[redacted] = None
                result = await collection.update_many(
                    {**query, "user_id": raw_user_id},
                    {"$set": updates},
                )
                modified += int(getattr(result, "modified_count", 0) or 0)
            entry["modified"] = modified

        report["collections"][name] = entry

    return report
