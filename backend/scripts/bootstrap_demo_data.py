#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.models.opportunity import Opportunity
from scripts.bootstrap_company_seeds import bootstrap_company_seeds


RAW_OPPORTUNITY_SEEDS: list[dict[str, Any]] = [
    {
        "title": "AI Product Engineering Intern",
        "organization": "VidyaVerse Labs",
        "domain": "ai",
        "opportunity_type": "internship",
        "work_mode": "hybrid",
        "location": "Bengaluru",
        "skills": ["python", "fastapi", "evaluation", "llm"],
        "stipend_min": 25000,
        "stipend_max": 45000,
    },
    {
        "title": "Data Science Research Fellow",
        "organization": "Ivy Analytics Institute",
        "domain": "data science",
        "opportunity_type": "research",
        "work_mode": "remote",
        "location": "Remote",
        "skills": ["python", "statistics", "experimentation", "sql"],
        "stipend_min": 30000,
        "stipend_max": 60000,
    },
    {
        "title": "Backend Platform Intern",
        "organization": "Cloud Systems Guild",
        "domain": "backend",
        "opportunity_type": "internship",
        "work_mode": "onsite",
        "location": "Hyderabad",
        "skills": ["python", "redis", "mongodb", "observability"],
        "stipend_min": 20000,
        "stipend_max": 40000,
    },
    {
        "title": "Cybersecurity Detection Trainee",
        "organization": "Aegis Security Studio",
        "domain": "cybersecurity",
        "opportunity_type": "training",
        "work_mode": "hybrid",
        "location": "Pune",
        "skills": ["security", "forensics", "network", "detection"],
        "stipend_min": 15000,
        "stipend_max": 30000,
    },
    {
        "title": "ML Infrastructure Challenge",
        "organization": "ModelOps Arena",
        "domain": "machine learning",
        "opportunity_type": "hackathon",
        "work_mode": "remote",
        "location": "Remote",
        "skills": ["mlops", "lightgbm", "feature store", "monitoring"],
        "stipend_min": 0,
        "stipend_max": 100000,
    },
    {
        "title": "Full Stack Fellowship",
        "organization": "Campus Builders Collective",
        "domain": "full stack",
        "opportunity_type": "fellowship",
        "work_mode": "hybrid",
        "location": "Delhi NCR",
        "skills": ["react", "nextjs", "fastapi", "product"],
        "stipend_min": 25000,
        "stipend_max": 50000,
    },
    {
        "title": "Quant Analytics Internship",
        "organization": "FinEdge Research",
        "domain": "finance",
        "opportunity_type": "internship",
        "work_mode": "onsite",
        "location": "Mumbai",
        "skills": ["python", "statistics", "finance", "dashboards"],
        "stipend_min": 35000,
        "stipend_max": 70000,
    },
    {
        "title": "Developer Relations Student Ambassador",
        "organization": "Open Source Cloud",
        "domain": "developer tools",
        "opportunity_type": "ambassador",
        "work_mode": "remote",
        "location": "Remote",
        "skills": ["open source", "community", "technical writing", "cloud"],
        "stipend_min": 10000,
        "stipend_max": 25000,
    },
]


def canonical_url(value: str) -> str:
    split = urlsplit(value.strip())
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(split.query, keep_blank_values=False)
            if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}
        ],
        doseq=True,
    )
    netloc = split.netloc.lower().removeprefix("www.")
    path = split.path.rstrip("/") or "/"
    return urlunsplit((split.scheme.lower() or "https", netloc, path, query, ""))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_seed_opportunity_payloads(*, limit: int | None = None) -> list[dict[str, Any]]:
    now = utc_now().replace(microsecond=0)
    rows: list[dict[str, Any]] = []
    for idx, seed in enumerate(RAW_OPPORTUNITY_SEEDS[: limit or None], start=1):
        slug = "-".join(str(seed["title"]).lower().replace("/", " ").split())
        url = canonical_url(f"https://demo.vidyaverse.local/opportunities/{slug}?utm_source=bootstrap")
        deadline = now + timedelta(days=14 + idx)
        skills = [str(skill).strip().lower() for skill in seed.get("skills", []) if str(skill).strip()]
        organization = str(seed["organization"]).strip()
        title = str(seed["title"]).strip()
        payload = {
            "title": title,
            "description": (
                f"{organization} is hiring for {title}. This seeded opportunity is designed for "
                "demo, staging, and model-bootstrap environments with realistic ranking metadata."
            ),
            "url": url,
            "canonical_url_hash": stable_hash(url),
            "canonical_key": stable_hash(f"{organization.lower()}::{title.lower()}::{seed['location']}"),
            "title_company_location_hash": stable_hash(f"{title.lower()}::{organization.lower()}::{seed['location']}"),
            "normalized_title": title.lower(),
            "normalized_organization": organization.lower(),
            "opportunity_type": seed["opportunity_type"],
            "portal_category": "seeded",
            "domain": seed["domain"],
            "university": "all",
            "source": "bootstrap_demo_data",
            "source_id": f"bootstrap-demo-{idx:03d}",
            "seen_on": ["bootstrap_demo_data"],
            "source_count": 1,
            "location": seed["location"],
            "work_mode": seed["work_mode"],
            "stipend": f"INR {seed['stipend_min']}-{seed['stipend_max']}/month",
            "stipend_min": seed["stipend_min"],
            "stipend_max": seed["stipend_max"],
            "stipend_currency": "INR",
            "stipend_period": "month",
            "eligibility": "Students, freshers, and early-career candidates.",
            "batch_years": [now.year, now.year + 1, now.year + 2],
            "tags": sorted(set([str(seed["domain"]).lower(), str(seed["opportunity_type"]).lower(), *skills])),
            "quality_score": 92.0,
            "quality_missing_fields": [],
            "last_quality_run_at": now,
            "trust_status": "verified",
            "trust_score": 88,
            "risk_score": 12,
            "risk_reasons": [],
            "verification_evidence": ["seeded_demo_fixture"],
            "lifecycle_status": "published",
            "opportunity_status": "active",
            "freshness_score": 0.95,
            "url_liveness_status": "alive",
            "url_last_checked_at": now,
            "published_at": now - timedelta(days=idx),
            "duration_start": now + timedelta(days=7),
            "duration_end": now + timedelta(days=60 + idx),
            "deadline": deadline,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }
        rows.append(payload)
    return rows


def _client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip().lower()
    if settings.MONGODB_TLS_FORCE or settings.ENVIRONMENT.strip().lower() == "production" or url.startswith("mongodb+srv://"):
        return {
            "tls": True,
            "tlsCAFile": certifi.where(),
            "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
        }
    return {}


async def bootstrap_demo_opportunities(*, limit: int, refresh_existing: bool, dry_run: bool) -> dict[str, Any]:
    payloads = build_seed_opportunity_payloads(limit=limit)
    if dry_run:
        return {"dry_run": True, "planned": len(payloads), "inserted": 0, "updated": 0, "skipped": 0}

    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=[Opportunity])
    inserted = 0
    updated = 0
    skipped = 0
    try:
        for payload in payloads:
            existing = await Opportunity.find_one(Opportunity.source_id == payload["source_id"])
            if existing is None:
                existing = await Opportunity.find_one(Opportunity.url == payload["url"])
            if existing is None:
                await Opportunity(**payload).insert()
                inserted += 1
                continue
            if not refresh_existing:
                skipped += 1
                continue
            for key, value in payload.items():
                setattr(existing, key, value)
            await existing.save()
            updated += 1
    finally:
        client.close()

    return {"dry_run": False, "planned": len(payloads), "inserted": inserted, "updated": updated, "skipped": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap deterministic demo data for lower environments and ML fixtures.")
    parser.add_argument("--opportunities", type=int, default=len(RAW_OPPORTUNITY_SEEDS))
    parser.add_argument("--skip-company-seeds", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    company_report = {"status": "skipped"}
    if not args.skip_company_seeds and not args.dry_run:
        company_report = await bootstrap_company_seeds()

    opportunity_report = await bootstrap_demo_opportunities(
        limit=max(1, int(args.opportunities)),
        refresh_existing=bool(args.refresh_existing),
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "company_seeds": company_report,
                "opportunities": opportunity_report,
                "next": "Run `python backend/scripts/bootstrap_ranking_pipeline.py --min-users 20 --days 14` to seed ranking interactions.",
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
