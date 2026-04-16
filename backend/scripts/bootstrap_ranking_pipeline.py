from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

# Keep script deterministic/light for CI/staging bootstraps.
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("OPENAI_API_KEY", "")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.experiment import Experiment, ExperimentAssignment
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.user import User
from app.services.experiment_service import experiment_service
from app.services.mlops.retraining_service import retraining_service
from app.services.ranking_model_service import ranking_model_service

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
SEED_PROFILE_TEMPLATES: list[dict[str, str]] = [
    {
        "bio": "Student interested in AI products and real-world impact.",
        "skills": "python machine learning nlp evaluation fastapi",
        "interests": "ai ml nlp research internship",
        "education": "B.Tech Computer Science",
    },
    {
        "bio": "Builder focused on cloud systems and developer tooling.",
        "skills": "devops kubernetes terraform monitoring backend",
        "interests": "cloud reliability distributed systems",
        "education": "B.E. Information Technology",
    },
    {
        "bio": "Data-focused learner interested in analytics and experimentation.",
        "skills": "sql analytics statistics experimentation dashboards",
        "interests": "data science quantitative finance",
        "education": "B.Sc. Data Science",
    },
    {
        "bio": "Security enthusiast exploring threat intel and incident response.",
        "skills": "security threat hunting network forensics detection",
        "interests": "cybersecurity research red team blue team",
        "education": "B.Tech Cyber Security",
    },
]


@dataclass(frozen=True)
class UserProfilePair:
    user: User
    profile: Profile


def _get_collection(document_cls: type) -> Any:
    getter = getattr(document_cls, "get_motor_collection", None)
    if callable(getter):
        return getter()
    getter = getattr(document_cls, "get_pymongo_collection", None)
    if callable(getter):
        return getter()
    raise AttributeError(f"No collection getter found for {document_cls.__name__}")


def _seed_password_placeholder() -> str:
    # Synthetic bootstrap users are not intended for interactive login.
    # Keep a deterministic marker instead of depending on passlib/bcrypt runtime.
    return f"seed-user::{secrets.token_hex(16)}"


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) >= 2}


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _ranking_mode_from_variant(variant: str) -> str:
    lowered = (variant or "").strip().lower()
    if lowered in {"baseline", "semantic", "ml", "ab"}:
        return lowered
    return "ab"


def _utc_now_naive() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _sample_event_time(*, now: datetime, days: int, rng: random.Random) -> datetime:
    safe_days = max(1, int(days))
    day_offset = rng.randint(0, safe_days - 1)
    second_offset = rng.randint(0, 86_399)
    return now - timedelta(days=day_offset, seconds=second_offset)


def _client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
    )
    if tls_needed:
        kwargs.update(
            {
                "tls": True,
                "tlsCAFile": certifi.where(),
                "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
            }
        )
    return kwargs


async def _init_db() -> AsyncIOMotorClient:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Profile,
            Opportunity,
            OpportunityInteraction,
            Experiment,
            ExperimentAssignment,
            RankingModelVersion,
        ],
    )
    return client


async def _ensure_seed_users(
    *,
    min_users: int,
    dry_run: bool,
) -> list[UserProfilePair]:
    users = await User.find_many(User.is_active == True).sort("created_at").to_list()  # noqa: E712
    profiles = await Profile.find_many().to_list()
    profile_by_user = {str(profile.user_id): profile for profile in profiles}

    pairs: list[UserProfilePair] = []
    for user in users:
        profile = profile_by_user.get(str(user.id))
        if profile:
            pairs.append(UserProfilePair(user=user, profile=profile))
    if len(pairs) >= min_users:
        return pairs[:min_users]

    if dry_run:
        return pairs

    need = int(min_users) - len(pairs)
    existing_emails = {user.email for user in users}
    created_pairs: list[UserProfilePair] = []
    template_count = len(SEED_PROFILE_TEMPLATES)

    for idx in range(need):
        serial = len(users) + idx + 1
        email = f"ab-seed-{serial}@vidyaverse.local"
        while email in existing_emails:
            serial += 1
            email = f"ab-seed-{serial}@vidyaverse.local"
        existing_emails.add(email)

        user = User(
            email=email,
            hashed_password=_seed_password_placeholder(),
            full_name=f"A/B Seed User {serial}",
            is_active=True,
            is_admin=False,
        )
        await user.insert()

        template = SEED_PROFILE_TEMPLATES[idx % template_count]
        profile = Profile(
            user_id=user.id,
            bio=template["bio"],
            skills=template["skills"],
            interests=template["interests"],
            education=template["education"],
            achievements="Bootstrapped profile for ranking experiment seeding.",
        )
        await profile.insert()
        created_pairs.append(UserProfilePair(user=user, profile=profile))

    return (pairs + created_pairs)[:min_users]


async def _seed_interactions(
    *,
    user_profiles: list[UserProfilePair],
    opportunities: list[Opportunity],
    variants: list[str],
    active_model_id: str | None,
    weights: dict[str, float],
    days: int,
    impressions_per_variant_per_day: int,
    clear_existing: bool,
    dry_run: bool,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(int(seed))
    now = _utc_now_naive()
    summary_counts: dict[str, dict[str, int]] = {
        variant: {"impressions": 0, "clicks": 0, "saves": 0, "applies": 0}
        for variant in variants
    }
    all_events: list[OpportunityInteraction] = []

    if clear_existing and not dry_run:
        await _get_collection(OpportunityInteraction).delete_many({"query": {"$regex": r"^bootstrap-ab:"}})

    parsed_opps: list[tuple[Opportunity, set[str], set[str]]] = []
    for opportunity in opportunities:
        text = " ".join(
            [
                opportunity.title or "",
                opportunity.description or "",
                opportunity.domain or "",
                opportunity.opportunity_type or "",
                opportunity.university or "",
            ]
        )
        parsed_opps.append((opportunity, _tokens(text), _tokens(opportunity.domain or "")))

    for pair in user_profiles:
        profile_tokens = _tokens(
            " ".join(
                [
                    pair.profile.bio or "",
                    pair.profile.skills or "",
                    pair.profile.interests or "",
                    pair.profile.education or "",
                    pair.profile.achievements or "",
                ]
            )
        )
        scored: list[tuple[Opportunity, int, int]] = []
        for opportunity, opp_tokens, domain_tokens in parsed_opps:
            overlap = len(profile_tokens.intersection(opp_tokens))
            domain_match = 1 if profile_tokens.intersection(domain_tokens) else 0
            scored.append((opportunity, overlap, domain_match))
        scored.sort(key=lambda row: (row[1], row[2], str(row[0].id)), reverse=True)

        for _day in range(max(1, int(days))):
            for variant in variants:
                for _ in range(max(1, int(impressions_per_variant_per_day))):
                    if variant in {"ml", "semantic"}:
                        pool = scored[: max(10, len(scored) // 3)]
                        rank_position = rng.randint(1, 10)
                    else:
                        pooled = scored[: max(20, len(scored) // 2)]
                        pool = pooled[min(6, len(pooled) - 1) :] if len(pooled) > 6 else pooled
                        rank_position = rng.randint(4, 25)

                    picked_opportunity, overlap, domain_match = rng.choice(pool or scored)

                    baseline_score = _clamp_score(28.0 + (overlap * 7.5) + rng.uniform(-6.0, 6.0))
                    semantic_bonus = 8.0 if variant in {"ml", "semantic"} else 0.0
                    semantic_score = _clamp_score(22.0 + (overlap * 9.0) + semantic_bonus + rng.uniform(-5.0, 5.0))
                    behavior_score = _clamp_score(18.0 + (16.0 if domain_match else 0.0) + rng.uniform(-7.0, 7.0))

                    ranking_mode = _ranking_mode_from_variant(variant)
                    match_score = _clamp_score(
                        (weights.get("semantic", 0.55) * semantic_score)
                        + (weights.get("baseline", 0.30) * baseline_score)
                        + (weights.get("behavior", 0.15) * behavior_score)
                    )

                    impression_at = _sample_event_time(now=now, days=days, rng=rng)
                    query_value = f"bootstrap-ab:{variant}:{rng.choice(['career', 'research', 'scholarship', 'hackathon'])}"

                    impression = OpportunityInteraction(
                        user_id=pair.user.id,
                        opportunity_id=picked_opportunity.id,
                        interaction_type="impression",
                        ranking_mode=ranking_mode,  # type: ignore[arg-type]
                        experiment_key="ranking_mode",
                        experiment_variant=variant,
                        query=query_value,
                        model_version_id=active_model_id,
                        rank_position=rank_position,
                        match_score=round(match_score, 3),
                        features={
                            "baseline_score": round(baseline_score, 3),
                            "semantic_score": round(semantic_score, 3),
                            "behavior_score": round(behavior_score, 3),
                            "skills_overlap_score": float(overlap),
                            "behavior_domain_pref": float(100.0 if domain_match else 0.0),
                            "behavior_type_pref": float(rng.uniform(0.0, 100.0)),
                        },
                        created_at=impression_at,
                    )
                    all_events.append(impression)
                    summary_counts[variant]["impressions"] += 1

                    ctr = 0.075 if variant == "baseline" else 0.118
                    save_rate = 0.028 if variant == "baseline" else 0.049
                    apply_given_click = 0.12 if variant == "baseline" else 0.16

                    click_logged = False
                    if rng.random() < ctr:
                        click_logged = True
                        click_event = OpportunityInteraction(
                            user_id=pair.user.id,
                            opportunity_id=picked_opportunity.id,
                            interaction_type="click",
                            ranking_mode=ranking_mode,  # type: ignore[arg-type]
                            experiment_key="ranking_mode",
                            experiment_variant=variant,
                            query=query_value,
                            model_version_id=active_model_id,
                            rank_position=rank_position,
                            match_score=round(match_score, 3),
                            created_at=impression_at + timedelta(minutes=rng.randint(1, 60)),
                        )
                        all_events.append(click_event)
                        summary_counts[variant]["clicks"] += 1

                    if rng.random() < save_rate:
                        save_event = OpportunityInteraction(
                            user_id=pair.user.id,
                            opportunity_id=picked_opportunity.id,
                            interaction_type="save",
                            ranking_mode=ranking_mode,  # type: ignore[arg-type]
                            experiment_key="ranking_mode",
                            experiment_variant=variant,
                            query=query_value,
                            model_version_id=active_model_id,
                            rank_position=rank_position,
                            match_score=round(match_score, 3),
                            created_at=impression_at + timedelta(minutes=rng.randint(5, 120)),
                        )
                        all_events.append(save_event)
                        summary_counts[variant]["saves"] += 1

                    if click_logged and rng.random() < apply_given_click:
                        apply_event = OpportunityInteraction(
                            user_id=pair.user.id,
                            opportunity_id=picked_opportunity.id,
                            interaction_type="apply",
                            ranking_mode=ranking_mode,  # type: ignore[arg-type]
                            experiment_key="ranking_mode",
                            experiment_variant=variant,
                            query=query_value,
                            model_version_id=active_model_id,
                            rank_position=rank_position,
                            match_score=round(match_score, 3),
                            created_at=impression_at + timedelta(minutes=rng.randint(20, 240)),
                        )
                        all_events.append(apply_event)
                        summary_counts[variant]["applies"] += 1

    if not dry_run and all_events:
        chunk = 1000
        for start in range(0, len(all_events), chunk):
            await OpportunityInteraction.insert_many(all_events[start : start + chunk])

    return {
        "dry_run": bool(dry_run),
        "variants": summary_counts,
        "total_events": int(len(all_events)),
        "seeded_users": int(len(user_profiles)),
        "seeded_days": int(days),
        "impressions_per_variant_per_day": int(impressions_per_variant_per_day),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap ranking A/B interactions, then optionally retrain + activate model.")
    parser.add_argument("--min-users", type=int, default=20)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--impressions-per-variant-per-day", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clear-existing", action="store_true", help="Delete previous bootstrap-ab interactions before seeding.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write interactions or users.")
    parser.add_argument("--run-retrain", action="store_true", help="Run retrain_and_register after seeding.")
    parser.add_argument("--auto-activate", action="store_true", help="Activate newly-trained model version.")
    parser.add_argument("--lookback-days", type=int, default=int(settings.MLOPS_RETRAIN_LOOKBACK_DAYS))
    parser.add_argument("--label-window-hours", type=int, default=int(settings.MLOPS_LABEL_WINDOW_HOURS))
    parser.add_argument("--min-rows", type=int, default=int(settings.MLOPS_MIN_TRAINING_ROWS))
    parser.add_argument("--grid-step", type=float, default=float(settings.MLOPS_TRAIN_GRID_STEP))
    args = parser.parse_args()

    client = await _init_db()
    try:
        await experiment_service.ensure_defaults()
        active = await ranking_model_service.ensure_active_model()
        experiment = await Experiment.find_one(Experiment.key == "ranking_mode")
        if not experiment:
            raise SystemExit("missing_experiment: ranking_mode")
        variants = [variant.name for variant in experiment.variants if variant.name]
        if not variants:
            variants = ["baseline", "ml"]

        opportunities = await Opportunity.find_many().to_list()
        if not opportunities:
            raise SystemExit("No opportunities found. Seed opportunities before bootstrapping interactions.")

        user_profiles = await _ensure_seed_users(min_users=max(1, int(args.min_users)), dry_run=bool(args.dry_run))
        if not user_profiles:
            raise SystemExit("No user profiles available. Run without --dry-run to auto-create seed users.")

        seed_report = await _seed_interactions(
            user_profiles=user_profiles,
            opportunities=opportunities,
            variants=variants,
            active_model_id=active.model_version_id,
            weights=active.weights,
            days=max(1, int(args.days)),
            impressions_per_variant_per_day=max(1, int(args.impressions_per_variant_per_day)),
            clear_existing=bool(args.clear_existing),
            dry_run=bool(args.dry_run),
            seed=int(args.seed),
        )

        payload: dict[str, Any] = {
            "status": "ok",
            "active_model_id": active.model_version_id,
            "active_weights": active.weights,
            "seed_report": seed_report,
        }

        if args.run_retrain:
            if args.dry_run:
                payload["retrain"] = {"status": "skipped", "reason": "dry_run"}
            else:
                result = await retraining_service.retrain_and_register(
                    lookback_days=max(1, int(args.lookback_days)),
                    label_window_hours=max(1, int(args.label_window_hours)),
                    min_rows=max(1, int(args.min_rows)),
                    grid_step=float(args.grid_step),
                    auto_activate=bool(args.auto_activate),
                    notes="bootstrap_ranking_pipeline",
                )
                payload["retrain"] = {
                    "status": "ok",
                    "training_rows": result.training_rows,
                    "weights": result.weights,
                    "metrics": result.metrics,
                    "window_start": result.window_start.isoformat(),
                    "window_end": result.window_end.isoformat(),
                    "auto_activated": bool(result.auto_activated),
                    "activation_reason": result.activation_reason,
                }

        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
