#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("OPENAI_API_KEY", "")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.core.config import settings
from app.models.experiment import Experiment, ExperimentVariant
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.user import User
from scripts.bootstrap_demo_data import build_seed_opportunity_payloads


PERSONAS = [
    ("ai", "python machine learning nlp llm evaluation", "remote", "Bangalore, India"),
    ("backend", "fastapi redis mongodb observability", "hybrid", "Hyderabad, India"),
    ("data science", "sql statistics experimentation dashboards", "remote", "Mumbai, India"),
    ("cybersecurity", "security forensics network detection", "hybrid", "Pune, India"),
    ("developer tools", "open source cloud technical writing", "remote", "Remote"),
]


def _client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip().lower()
    if settings.MONGODB_TLS_FORCE or settings.ENVIRONMENT.strip().lower() == "production" or url.startswith("mongodb+srv://"):
        return {"tls": True, "tlsCAFile": certifi.where(), "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS)}
    return {}


async def _init_db() -> AsyncIOMotorClient:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[User, Profile, Opportunity, OpportunityInteraction, Experiment],
    )
    return client


async def _ensure_opportunities(*, min_count: int) -> list[Opportunity]:
    existing = await Opportunity.find_many(Opportunity.source == "bootstrap_demo_data").to_list()
    if len(existing) >= min_count:
        return existing[:min_count]
    for payload in build_seed_opportunity_payloads(limit=max(min_count, 8)):
        if await Opportunity.find_one(Opportunity.source_id == payload["source_id"]):
            continue
        await Opportunity(**payload).insert()
    return await Opportunity.find_many(Opportunity.source == "bootstrap_demo_data").to_list()


async def _ensure_candidate_users(*, count: int) -> list[tuple[User, Profile]]:
    pairs: list[tuple[User, Profile]] = []
    for idx in range(1, count + 1):
        domain, skills, work_mode, location = PERSONAS[(idx - 1) % len(PERSONAS)]
        email = f"seed-candidate-{idx:02d}@vidyaverse.local"
        user = await User.find_one(User.email == email)
        if user is None:
            user = User(email=email, hashed_password="SEED_TEST_NO_PASSWORD", full_name=f"Seed Candidate {idx}", account_type="candidate")
            await user.insert()
        profile = await Profile.find_one(Profile.user_id == user.id)
        if profile is None:
            profile = Profile(
                user_id=user.id,
                account_type="candidate",
                first_name="Seed",
                last_name=f"Candidate {idx}",
                domains_of_interest=[domain],
                preferred_work_mode=work_mode,
                preferred_locations=location,
                skills=skills,
                interests=domain,
                opportunity_types=["internship", "hackathon", "research"],
                onboarding_completed=True,
                onboarding_completed_at=utc_now(),
                cold_start_quality_score=0.9,
            )
            await profile.insert()
        pairs.append((user, profile))
    return pairs


async def _ensure_employers(*, count: int, opportunities_per_employer: int) -> int:
    inserted = 0
    now = utc_now().replace(microsecond=0)
    for idx in range(1, count + 1):
        email = f"seed-employer-{idx:02d}@vidyaverse.local"
        user = await User.find_one(User.email == email)
        if user is None:
            user = User(email=email, hashed_password="SEED_TEST_NO_PASSWORD", full_name=f"Seed Employer {idx}", account_type="employer")
            await user.insert()
        if await Profile.find_one(Profile.user_id == user.id) is None:
            await Profile(user_id=user.id, account_type="employer", company_name=f"Seed Employer {idx}", onboarding_completed=True).insert()
        for slot in range(1, opportunities_per_employer + 1):
            source_id = f"seed-employer-{idx:02d}-opp-{slot:02d}"
            if await Opportunity.find_one(Opportunity.source_id == source_id):
                continue
            await Opportunity(
                title=f"Employer Seed Role {slot}",
                description="Synthetic employer-posted role for staging and integration tests.",
                url=f"https://demo.vidyaverse.local/employers/{idx}/opportunities/{slot}",
                source="seed_test_data",
                source_id=source_id,
                domain="full stack",
                opportunity_type="internship",
                work_mode="hybrid",
                location="India",
                tags=["python", "react", "fastapi"],
                quality_score=85.0,
                trust_status="verified",
                trust_score=82,
                risk_score=10,
                lifecycle_status="published",
                opportunity_status="active",
                freshness_score=0.9,
                posted_by_user_id=user.id,
                is_employer_post=True,
                deadline=now + timedelta(days=30 + slot),
                published_at=now,
            ).insert()
            inserted += 1
    return inserted


async def _ensure_experiments() -> int:
    definitions = [
        ("ranking_control_vs_ml", "Control vs ML ranking", "ml"),
        ("ranking_control_vs_semantic", "Control vs Semantic ranking", "semantic"),
    ]
    created = 0
    for key, name, treatment_mode in definitions:
        if await Experiment.find_one(Experiment.key == key):
            continue
        await Experiment(
            key=key,
            name=name,
            description="Synthetic staging experiment seeded for release validation.",
            status="running",
            variants=[
                ExperimentVariant(name="control", ranking_mode="baseline", traffic_fraction=0.5, is_control=True),
                ExperimentVariant(name="treatment", ranking_mode=treatment_mode, traffic_fraction=0.5),
            ],
            start_date=utc_now(),
            min_sample_size=200,
            primary_metric="ctr",
            guardrail_metrics=["apply_rate", "save_rate"],
            default_variant="control",
        ).insert()
        created += 1
    return created


async def _seed_interactions(*, user_profiles: list[tuple[User, Profile]], opportunities: list[Opportunity], seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    now = utc_now().replace(microsecond=0)
    inserted = 0
    positives = 0
    existing = await OpportunityInteraction.find_many({"query": {"$regex": r"^seed-test:"}}).count()
    if existing:
        return {"inserted": 0, "positive_pairs": int(await OpportunityInteraction.find_many({"query": {"$regex": r"^seed-test:"}, "reward": {"$gte": 0.6}}).count())}
    for user, profile in user_profiles:
        preferred = set(profile.domains_of_interest or [])
        for shown_idx in range(150):
            preferred_pool = [opp for opp in opportunities if str(opp.domain or "").lower() in preferred]
            pool = preferred_pool if preferred_pool and rng.random() < 0.8 else opportunities
            opp = rng.choice(pool)
            created_at = now - timedelta(days=rng.randint(0, 21), minutes=rng.randint(0, 1440))
            rank = rng.randint(1, 30)
            await OpportunityInteraction(
                user_id=user.id,
                opportunity_id=opp.id,
                interaction_type="impression",
                event_type="impression",
                reward=0.0,
                ranking_mode="ab",
                experiment_key="ranking_control_vs_ml",
                experiment_variant="treatment" if rng.random() < 0.5 else "control",
                query="seed-test:feed",
                rank_position=rank,
                referrer_rank=rank,
                cold_start=False,
                traffic_type="synthetic",
                created_at=created_at,
            ).insert()
            inserted += 1
            roll = rng.random()
            if roll < 0.15:
                reward = 0.75 if roll < 0.02 else 0.6 if roll < 0.05 else 0.2
                event = "apply_complete" if reward >= 0.75 else "save" if reward >= 0.6 else "click"
                await OpportunityInteraction(
                    user_id=user.id,
                    opportunity_id=opp.id,
                    interaction_type=event,
                    event_type=event,
                    reward=reward,
                    dwell_time_ms=rng.randint(5_000, 60_000),
                    scroll_depth=rng.uniform(40, 100),
                    ranking_mode="ab",
                    experiment_key="ranking_control_vs_ml",
                    experiment_variant="treatment",
                    query="seed-test:feed",
                    rank_position=rank,
                    referrer_rank=rank,
                    cold_start=False,
                    traffic_type="synthetic",
                    created_at=created_at + timedelta(minutes=rng.randint(1, 120)),
                ).insert()
                inserted += 1
                if reward >= 0.6:
                    positives += 1
    return {"inserted": inserted, "positive_pairs": positives}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = await _init_db()
    try:
        opportunities = await _ensure_opportunities(min_count=max(8, int(args.min_opportunities)))
        user_profiles = await _ensure_candidate_users(count=max(1, int(args.users)))
        employers_inserted = await _ensure_employers(count=max(0, int(args.employers)), opportunities_per_employer=3)
        experiments_created = await _ensure_experiments()
        interactions = await _seed_interactions(user_profiles=user_profiles, opportunities=opportunities, seed=int(args.seed))
        return {
            "status": "ok",
            "users": len(user_profiles),
            "opportunities_available": len(opportunities),
            "employer_opportunities_inserted": employers_inserted,
            "experiments_created": experiments_created,
            "interactions": interactions,
        }
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic staging/test data for ranking and product flows.")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--employers", type=int, default=5)
    parser.add_argument("--min-opportunities", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
