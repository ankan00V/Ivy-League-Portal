from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.models.application import Application
from app.models.experiment import Experiment, ExperimentAssignment
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.user import User
from app.services.telemetry_privacy import get_collection

MARKER_START = "<!-- DATASET_SNAPSHOT:START -->"
MARKER_END = "<!-- DATASET_SNAPSHOT:END -->"


async def _collect_snapshot_postgres() -> dict[str, Any]:
    """Same snapshot, read from Postgres with SQL.

    A separate implementation rather than a shared one because `pg_documents.install`
    patches the Beanie *query* API (`find_many`, `find_one`, …) but not
    `get_motor_collection`. The Mongo path below reaches for the raw collection to
    run `distinct` and `aggregate`, and under the Postgres ODM that handle still
    points at Mongo — it would return numbers from the abandoned database while
    looking like it worked.
    """
    import asyncpg

    generated_at = utc_now()
    conn = await asyncpg.connect(
        settings.SUPABASE_DATABASE_URL,
        timeout=30,
        # The Supabase pooler runs pgbouncer in transaction mode, which does not
        # support prepared statements.
        statement_cache_size=0,
    )
    try:
        async def scalar(sql: str) -> int:
            return int(await conn.fetchval(sql) or 0)

        def _label(value: Any) -> str:
            """Strip JSON encoding from enum-ish columns.

            `pg_documents` maps Literal/enum string fields onto `json` columns, so
            `interaction_type` physically stores `"impression"` — quote characters
            included. Rendered raw, the README reads `"impression" 30,132`. Note
            this also means SQL like `WHERE interaction_type = 'impression'` fails
            outright with `invalid input syntax for type json`.
            """
            if value is None:
                return "unlabelled"
            text = str(value).strip()
            if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
                text = text[1:-1]
            return text or "unlabelled"

        async def breakdown(sql: str) -> dict[str, int]:
            merged: dict[str, int] = {}
            for r in await conn.fetch(sql):
                key = _label(r["k"])
                merged[key] = merged.get(key, 0) + int(r["n"])
            return merged

        statuses = await breakdown(
            'SELECT opportunity_status AS k, count(*) n FROM app."opportunities" GROUP BY 1'
        )
        return {
            "generated_at": generated_at.isoformat(),
            "snapshot_date": generated_at.strftime("%B %d, %Y"),
            "backend": "postgres",
            "counts": {
                "opportunities": sum(statuses.values()),
                "opportunities_active": statuses.get("active", 0),
                "opportunities_expired": statuses.get("expired", 0),
                "opportunities_removed": statuses.get("removed", 0),
                "applications": await scalar('SELECT count(*) FROM app."applications"'),
                "opportunity_interactions": await scalar(
                    'SELECT count(*) FROM app."opportunity_interactions"'
                ),
                "interaction_distinct_users": await scalar(
                    'SELECT count(DISTINCT user_id) FROM app."opportunity_interactions"'
                ),
                "experiments": await scalar('SELECT count(*) FROM app."experiments"'),
                "experiment_assignments": await scalar(
                    'SELECT count(*) FROM app."experiment_assignments"'
                ),
                "ranking_model_versions": await scalar(
                    'SELECT count(*) FROM app."ranking_model_versions"'
                ),
                "drift_reports": await scalar('SELECT count(*) FROM app."model_drift_reports"'),
                "profiles": await scalar('SELECT count(*) FROM app."profiles"'),
                "users": await scalar('SELECT count(*) FROM app."users"'),
            },
            "interaction_traffic_type": await breakdown(
                'SELECT traffic_type AS k, count(*) n FROM app."opportunity_interactions" GROUP BY 1'
            ),
            "interaction_events": await breakdown(
                'SELECT interaction_type AS k, count(*) n FROM app."opportunity_interactions" GROUP BY 1'
            ),
            "source_distribution": dict(
                sorted(
                    (await breakdown(
                        'SELECT lower(coalesce(nullif(trim(source), \'\'), \'unknown\')) AS k, '
                        'count(*) n FROM app."opportunities" GROUP BY 1'
                    )).items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        }
    finally:
        await conn.close()


async def _collect_snapshot() -> dict[str, Any]:
    """Collect the numbers, with the qualifiers that keep them from misleading.

    Two of these used to be published bare, and both invited the wrong reading.

    `opportunities` counted every row regardless of status, so retired and expired
    listings were reported as if they were the live corpus. They are now split.

    `opportunity_interactions` was worse. A single figure under a heading that says
    "Dataset Size" reads as user engagement, and on 2026-08-10 every one of the
    30,083 rows on Atlas belonged to **one** account. Reporting that number without
    the distinct-user count beside it would repeat, in a third form, the defect this
    repo has already published twice: a metric that is arithmetically true and
    substantively false. The traffic_type split is here for the same reason —
    Atlas has never had the provenance backfill run against it, so a "real" label
    there means "not yet audited", not "verified genuine".
    """
    generated_at = utc_now()
    opportunities = await Opportunity.find_many().to_list()
    source_counter = Counter(
        str(getattr(item, "source", "") or "unknown").strip().lower() or "unknown"
        for item in opportunities
    )

    status_counter = Counter(
        str(getattr(item, "opportunity_status", "") or "unknown").strip().lower() or "unknown"
        for item in opportunities
    )

    # get_collection, not get_motor_collection: Beanie 2.x renamed the accessor,
    # and calling the old name here would raise AttributeError at snapshot time.
    interactions = get_collection(OpportunityInteraction)
    interaction_total = int(await interactions.count_documents({}))
    interaction_users = len(await interactions.distinct("user_id"))
    traffic_counter: dict[str, int] = {}
    async for row in interactions.aggregate(
        [{"$group": {"_id": "$traffic_type", "n": {"$sum": 1}}}]
    ):
        traffic_counter[str(row.get("_id") or "unlabelled")] = int(row.get("n") or 0)

    event_counter: dict[str, int] = {}
    async for row in interactions.aggregate(
        [{"$group": {"_id": "$interaction_type", "n": {"$sum": 1}}}]
    ):
        event_counter[str(row.get("_id") or "unknown")] = int(row.get("n") or 0)

    return {
        "generated_at": generated_at.isoformat(),
        "snapshot_date": generated_at.strftime("%B %d, %Y"),
        "counts": {
            "opportunities": len(opportunities),
            "opportunities_active": int(status_counter.get("active", 0)),
            "opportunities_expired": int(status_counter.get("expired", 0)),
            "opportunities_removed": int(status_counter.get("removed", 0)),
            "applications": int(await Application.find_many().count()),
            "opportunity_interactions": interaction_total,
            "interaction_distinct_users": interaction_users,
            "experiments": int(await Experiment.find_many().count()),
            "experiment_assignments": int(await ExperimentAssignment.find_many().count()),
            "ranking_model_versions": int(await RankingModelVersion.find_many().count()),
            "drift_reports": int(await ModelDriftReport.find_many().count()),
            "profiles": int(await Profile.find_many().count()),
            "users": int(await User.find_many().count()),
        },
        "interaction_traffic_type": dict(sorted(traffic_counter.items(), key=lambda i: (-i[1], i[0]))),
        "interaction_events": dict(sorted(event_counter.items(), key=lambda i: (-i[1], i[0]))),
        "source_distribution": dict(sorted(source_counter.items(), key=lambda item: (-item[1], item[0]))),
    }


def _build_markdown(snapshot: dict[str, Any]) -> str:
    counts = dict(snapshot.get("counts") or {})
    source_distribution = dict(snapshot.get("source_distribution") or {})
    traffic = dict(snapshot.get("interaction_traffic_type") or {})
    events = dict(snapshot.get("interaction_events") or {})
    interaction_users = int(counts.get("interaction_distinct_users") or 0)
    interaction_total = int(counts.get("opportunity_interactions") or 0)

    lines = [
        "## Dataset Size (Verified Snapshot)",
        f"Snapshot date: **{snapshot.get('snapshot_date') or 'n/a'}**",
        "",
        "This is a count of rows in the database. It is **not** a measure of usage,",
        "and the interaction figures below are qualified for that reason.",
        "",
        f"- Opportunities: **{int(counts.get('opportunities') or 0):,}** total "
        f"({int(counts.get('opportunities_active') or 0):,} active, "
        f"{int(counts.get('opportunities_expired') or 0):,} expired, "
        f"{int(counts.get('opportunities_removed') or 0):,} retired)",
        f"- Applications: **{int(counts.get('applications') or 0):,}**",
        f"- Users: **{int(counts.get('users') or 0):,}**",
        f"- Profiles: **{int(counts.get('profiles') or 0):,}**",
        f"- Experiments: **{int(counts.get('experiments') or 0):,}**",
        f"- Experiment assignments: **{int(counts.get('experiment_assignments') or 0):,}**",
        f"- Ranking model versions: **{int(counts.get('ranking_model_versions') or 0):,}**",
        f"- Drift reports: **{int(counts.get('drift_reports') or 0):,}**",
        "",
        f"- Opportunity interactions: **{interaction_total:,}**, "
        f"generated by **{interaction_users:,} distinct account"
        f"{'' if interaction_users == 1 else 's'}**.",
    ]

    if interaction_users <= 2 and interaction_total > 100:
        lines.append(
            f"  Read that pairing before quoting the row count: {interaction_total:,} rows "
            f"across {interaction_users} account{'' if interaction_users == 1 else 's'} is "
            "developer activity, not student traffic."
        )

    if events:
        lines.append(
            "  By event: "
            + ", ".join(f"{name} {count:,}" for name, count in events.items())
            + "."
        )

    if traffic:
        lines.append(
            "  By provenance label: "
            + ", ".join(f"`{name}` {count:,}" for name, count in traffic.items())
            + ". A `real` label means the row has not been audited, not that it has "
            "been verified genuine — see `app/models/traffic.py`."
        )

    # The registry passed 200 sources once the company-board rotation filled in, and
    # a 200-line list buries every other fact in this section. Top N only, with the
    # remainder stated rather than silently dropped — the full breakdown is in the
    # JSON artifact this script writes alongside the README.
    top_n = 20
    ranked = list(source_distribution.items())
    lines += [
        "",
        f"Top {top_n} sources by opportunity count (all statuses; "
        f"{len(ranked):,} sources total, full breakdown in "
        "`backend/benchmarks/dataset_snapshot_latest.json`):",
    ]
    for source, count in ranked[:top_n]:
        lines.append(f"- `{source}`: {int(count):,}")

    tail = ranked[top_n:]
    if tail:
        tail_rows = sum(int(count) for _, count in tail)
        lines.append(
            f"- _...and {len(tail):,} further sources contributing {tail_rows:,} "
            "opportunities between them._"
        )
    return "\n".join(lines).strip()


def _upsert_readme_section(*, readme_path: Path, markdown: str) -> bool:
    content = readme_path.read_text(encoding="utf-8")
    if MARKER_START not in content or MARKER_END not in content:
        return False
    start = content.index(MARKER_START) + len(MARKER_START)
    end = content.index(MARKER_END)
    updated = content[:start] + "\n\n" + markdown + "\n\n" + content[end:]
    readme_path.write_text(updated, encoding="utf-8")
    return True


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Publish dataset snapshot metrics into README and a JSON artifact.")
    parser.add_argument(
        "--readme",
        type=str,
        default=str(REPO_ROOT / "README.md"),
        help="README file containing DATASET_SNAPSHOT markers.",
    )
    parser.add_argument(
        "--artifact",
        type=str,
        default=str(BACKEND_ROOT / "benchmarks" / "dataset_snapshot_latest.json"),
        help="Output JSON artifact path.",
    )
    args = parser.parse_args()

    models = [
        Opportunity,
        Application,
        OpportunityInteraction,
        Experiment,
        ExperimentAssignment,
        RankingModelVersion,
        ModelDriftReport,
        Profile,
        User,
    ]

    # Read whichever database is actually serving.
    #
    # This script used to connect to Mongo unconditionally, which was correct
    # until it wasn't: after the Postgres cutover it kept publishing a "Verified
    # Snapshot" measured against an abandoned Atlas database that had taken no
    # write since 2026-06-18, while the live corpus grew in Postgres. A snapshot
    # that reports the wrong database with a confident heading is precisely the
    # class of number this repo has published before and should not publish again.
    client = None
    if settings.POSTGRES_ODM_ENABLED:
        from app.db import pg_documents

        pg_documents.install(models)
    else:
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=models)
    try:
        snapshot = (
            await _collect_snapshot_postgres()
            if settings.POSTGRES_ODM_ENABLED
            else await _collect_snapshot()
        )
        markdown = _build_markdown(snapshot)

        readme_path = Path(args.readme)
        artifact_path = Path(args.artifact)
        if not artifact_path.is_absolute():
            artifact_path = REPO_ROOT / artifact_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")

        ok = _upsert_readme_section(readme_path=readme_path, markdown=markdown)
        if not ok:
            raise RuntimeError(
                f"README section markers missing. Add {MARKER_START} ... {MARKER_END} to {readme_path}."
            )

        print(
            json.dumps(
                {
                    "status": "ok",
                    "readme": str(readme_path),
                    "artifact": str(artifact_path),
                    "snapshot_date": snapshot.get("snapshot_date"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        # None when reading Postgres: no Mongo connection was opened.
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
