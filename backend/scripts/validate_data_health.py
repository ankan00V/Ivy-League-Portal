#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.user import User


def _client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip().lower()
    if settings.MONGODB_TLS_FORCE or settings.ENVIRONMENT.strip().lower() == "production" or url.startswith("mongodb+srv://"):
        return {"tls": True, "tlsCAFile": certifi.where(), "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS)}
    return {}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=[Opportunity, OpportunityInteraction, User])
    try:
        active_query = {
            "lifecycle_status": "published",
            "opportunity_status": {"$in": ["active", "closing_soon"]},
        }
        active = await Opportunity.find_many(active_query).to_list()
        url_missing = [str(row.id) for row in active if not str(row.url or "").startswith(("http://", "https://"))]
        duplicate_hashes = [
            key for key, count in Counter(str(row.canonical_url_hash or row.url) for row in active).items() if key and count > 1
        ]
        low_quality_active = [str(row.id) for row in active if float(row.quality_score or 0.0) < 10.0]
        missing_embeddings = [str(row.id) for row in active if not row.embedding]
        users = await User.find_many().to_list()
        users_missing_embeddings: list[str] = []
        for user in users:
            interactions = await OpportunityInteraction.find_many(OpportunityInteraction.user_id == user.id).count()
            if interactions > 5 and not user.profile_embedding:
                users_missing_embeddings.append(str(user.id))
        positive_pairs = await OpportunityInteraction.find_many({"reward": {"$gte": 0.6}}).count()
        checks = {
            "active_opportunities": len(active),
            "missing_apply_url": len(url_missing),
            "duplicate_canonical_urls": len(duplicate_hashes),
            "low_quality_active": len(low_quality_active),
            "active_missing_embeddings": len(missing_embeddings),
            "users_missing_embeddings_after_5_interactions": len(users_missing_embeddings),
            "positive_training_pairs": int(positive_pairs),
        }
        failures = []
        if checks["missing_apply_url"]:
            failures.append("active opportunities missing apply URL")
        if checks["duplicate_canonical_urls"]:
            failures.append("duplicate canonical URLs among active opportunities")
        if checks["low_quality_active"]:
            failures.append("active opportunities with quality_score < 10")
        if checks["active_missing_embeddings"] and not args.allow_missing_embeddings:
            failures.append("active opportunities missing embeddings")
        if checks["users_missing_embeddings_after_5_interactions"] and not args.allow_missing_embeddings:
            failures.append("users with >5 interactions missing embeddings")
        if checks["positive_training_pairs"] < int(args.min_positive_pairs):
            failures.append(f"positive training pairs below {int(args.min_positive_pairs)}")
        return {"status": "ok" if not failures else "failed", "checks": checks, "failures": failures}
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate opportunity and training-signal data health.")
    parser.add_argument("--min-positive-pairs", type=int, default=100)
    parser.add_argument("--allow-missing-embeddings", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(_run(args))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
