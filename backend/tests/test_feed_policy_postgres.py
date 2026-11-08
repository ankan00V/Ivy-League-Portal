import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

import asyncpg
import pytest

from app.core.config import settings
from app.repositories import opportunity_repository as repository
from app.services.feed_policy import listing_quality_sql, listing_rejection_reason, portal_sql, resolve_portal, resolved_type, resolved_type_sql
from tests.test_feed_policy import CASES, record_for


@pytest.fixture(scope="module")
def isolated_postgres():
    candidates = [shutil.which("pg_ctl"), "/opt/homebrew/opt/postgresql@16/bin/pg_ctl"]
    executable = next((Path(path) for path in candidates if path and Path(path).is_file()), None)
    if executable is None or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("An unprivileged local PostgreSQL installation is required")
    with tempfile.TemporaryDirectory(prefix="vv-feed-", dir="/tmp") as directory:
        data = str(Path(directory) / "data")
        subprocess.run([str(executable.with_name("initdb")), "-D", data, "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, capture_output=True, timeout=30)
        subprocess.run([str(executable), "-D", data, "-l", str(Path(directory) / "postgres.log"), "-o", f"-F -k {directory} -c listen_addresses=''", "-w", "start"], check=True, capture_output=True, timeout=30)
        try:
            yield directory
        finally:
            subprocess.run([str(executable), "-D", data, "-m", "fast", "-w", "stop"], check=True, capture_output=True, timeout=30)


def test_python_and_postgres_policy_parity(isolated_postgres):
    async def check():
        connection = await asyncpg.connect(host=isolated_postgres, database="postgres")
        try:
            rows = [record_for(title, url, kind) for title, url, kind, _ in CASES]
            rows.extend([
                record_for("Conference Coordinator", "https://example.com/role/12", "Job") | {"portal_category": "competitive"},
                record_for("Research Engineer", "https://example.com/role/12", "Research"),
                record_for("Example Board", "https://example.com/role/12", "Job") | {"source": "example_board"},
                record_for("Python Intern", "https://example.com/role/12", "Internship") | {"url_liveness_status": "dead"},
            ])
            policy = " AND ".join(listing_quality_sql(settings.OPPORTUNITY_SCOPE_TYPES))
            results = await connection.fetch(
                f"SELECT title, ({resolved_type_sql()}) AS kind, ({portal_sql()}) AS portal, ({policy}) AS visible FROM jsonb_to_recordset($1::jsonb) AS listing(title text, url text, source text, opportunity_type text, portal_category text, url_liveness_status text)",
                json.dumps(rows),
            )
            for row, result in zip(rows, results, strict=True):
                assert result["visible"] == (listing_rejection_reason(row, allowed_types=settings.OPPORTUNITY_SCOPE_TYPES) is None), row["title"]
                assert result["kind"] == resolved_type(row["opportunity_type"], row["title"]), row["title"]
                assert result["portal"] == resolve_portal(row["opportunity_type"], row["title"], row["portal_category"]), row["title"]
        finally:
            await connection.close()
    asyncio.run(check())


def test_page_totals_facets_and_speciality_filters(isolated_postgres):
    async def check():
        pool = await asyncpg.create_pool(host=isolated_postgres, database="postgres", min_size=1, max_size=2)
        try:
            columns = [column.strip() for column in repository._SELECT.split(",")]
            date_columns = {"deadline", "duration_start", "duration_end"}
            array_columns = {"tags", "seen_on"}
            numeric_columns = {"trust_score", "risk_score", "quality_score", "freshness_score", "dedup_score", "source_count", "duplicate_count", "stipend_min", "stipend_max", "duration_months"}
            declarations = []
            for column in columns:
                kind = "text"
                if column.endswith("_at") or column in date_columns:
                    kind = "timestamptz"
                elif column in array_columns:
                    kind = "text[]"
                elif column == "batch_years":
                    kind = "integer[]"
                elif column in numeric_columns:
                    kind = "numeric"
                elif column in {"is_employer_post", "quality_review_required"}:
                    kind = "boolean"
                elif column == "extras":
                    kind = "jsonb"
                declarations.append(f"{column} {kind}")
            async with pool.acquire() as connection:
                await connection.execute("CREATE SCHEMA app")
                await connection.execute("CREATE TABLE app.opportunities (" + ",".join(declarations) + ", role_track text, feed_categories text[])")
                rows = [
                    ("Internshala", "Internship", "career", "active", "https://internshala.com/internships"),
                    ("Retail Sales Intern", "Internship", "career", "active", "https://example.com/role/1"),
                    ("AI Engineering Intern", "Internship", "competitive", "closing_soon", "https://example.com/role/2"),
                    ("Python Workshop for Engineers", "Workshop", "career", "active", "https://example.com/events/python"),
                ]
                for index, (title, kind, portal, status, url) in enumerate(rows):
                    await connection.execute("INSERT INTO app.opportunities (legacy_mongo_id, title, description, url, opportunity_type, portal_category, opportunity_status, source, role_track, feed_categories) VALUES ($1,$2,'Build projects with Python.',$3,$4,$5,$6,'fixture','technical',ARRAY['remote'])", f"{index + 1:024x}", title, url, kind, portal, status)
            with patch.object(repository, "get_pool", return_value=pool):
                career, total = await repository.load_opportunity_page(portal="career", per_page=1)
                second, second_total = await repository.load_opportunity_page(portal="career", per_page=1, page=2)
                assert total == second_total == 2
                assert len(career) == len(second) == 1
                assert career[0].id != second[0].id
                events, event_total = await repository.load_opportunity_page(portal="competitive")
                assert event_total == len(events) == 1
                assert events[0].portal_category == "competitive"
                assert events[0].opportunity_type == "Workshop"
                ai_rows, ai_total = await repository.load_opportunity_page(portal="career", specialities=["ai"])
                assert ai_total == len(ai_rows) == 1
                assert ai_rows[0].title == "AI Engineering Intern"
                facets = await repository.feed_facet_counts(portal="career")
                assert facets["tracks"]["all"] == 2
                assert facets["placements"]["remote"] == 2
        finally:
            await pool.close()
    asyncio.run(check())
