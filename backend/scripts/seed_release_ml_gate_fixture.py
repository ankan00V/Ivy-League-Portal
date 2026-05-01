from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from beanie import PydanticObjectId, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.experiment import Experiment
from app.models.feature_store_row import FeatureStoreRow
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.user import User


CI_DB_MARKERS = ("ci", "test", "fixture", "release_gate")


def _is_safe_fixture_db(name: str) -> bool:
    normalized = (name or "").strip().lower()
    return bool(normalized) and any(marker in normalized for marker in CI_DB_MARKERS)


def _created_at(index: int, *, days: int):
    return utc_now() - timedelta(days=(index % max(1, days)), minutes=index % 60)


async def _insert_many(documents: list[Any]) -> int:
    if not documents:
        return 0
    await type(documents[0]).insert_many(documents)
    return len(documents)


async def _seed_users_and_opportunities(*, days: int) -> tuple[list[User], list[Opportunity]]:
    users: list[User] = []
    profiles: list[Profile] = []
    for index in range(40):
        user_id = PydanticObjectId()
        user = User(
            id=user_id,
            email=f"release-gate-user-{index}@example.com",
            hashed_password="not-used-in-ci-fixture",
            full_name=f"Release Gate User {index}",
            username=f"release_gate_user_{index}",
            account_type="candidate",
            auth_provider="password",
            is_active=True,
            created_at=_created_at(index, days=days),
        )
        users.append(user)
        profiles.append(
            Profile(
                user_id=user_id,
                account_type="candidate",
                first_name="Release",
                last_name=f"Gate {index}",
                user_type="college_student" if index % 2 else "professional",
                domain=["engineering", "research", "policy", "finance"][index % 4],
                course="Computer Science",
                college_name=["Harvard", "Yale", "Princeton", "Columbia"][index % 4],
                preferred_locations=["Boston", "New Haven", "Princeton", "New York"][index % 4],
                consent_data_processing=True,
                onboarding_completed=True,
                incoscore=80.0 + float(index % 10),
            )
        )

    opportunities: list[Opportunity] = []
    for index in range(90):
        created_at = _created_at(index, days=days)
        opportunities.append(
            Opportunity(
                title=f"Release Gate Opportunity {index}",
                description=(
                    "Deterministic CI opportunity for ranking parity, model promotion, "
                    "feature freshness, and DS operating-loop release gates."
                ),
                url=f"https://example.com/release-gate/opportunities/{index}",
                opportunity_type=["internship", "research", "fellowship"][index % 3],
                portal_category="ci-release-gate",
                domain=["engineering", "research", "policy", "finance"][index % 4],
                university=["Harvard", "Yale", "Princeton", "Columbia"][index % 4],
                source="ci_release_gate_fixture",
                location=["Boston", "New Haven", "Princeton", "New York"][index % 4],
                eligibility="Open to verified candidates in the CI fixture.",
                lifecycle_status="published",
                published_at=created_at,
                lifecycle_updated_at=created_at,
                deadline=utc_now() + timedelta(days=30 + (index % 30)),
                created_at=created_at,
                updated_at=created_at,
                last_seen_at=utc_now(),
            )
        )

    await _insert_many(users)
    await _insert_many(profiles)
    await _insert_many(opportunities)
    return users, opportunities


async def _seed_models(*, days: int) -> tuple[RankingModelVersion, RankingModelVersion]:
    now = utc_now()
    champion = RankingModelVersion(
        name="release-gate-champion",
        is_active=True,
        weights={"semantic_score": 0.48, "baseline_score": 0.42, "behavior_score": 0.10},
        metrics={
            "auc_default": 0.720,
            "auc_learned": 0.744,
            "auc_gain": 0.024,
            "auc_gain_test": 0.024,
            "precision_at_10": 0.68,
        },
        trained_window_start=now - timedelta(days=days),
        trained_window_end=now - timedelta(days=2),
        training_rows=4800,
        feature_schema={"semantic_score": "float", "baseline_score": "float", "behavior_score": "float"},
        serving_ready=True,
        lifecycle={"status": "approved", "activation_reason": "ci release gate champion"},
        training_metadata={"source": "release_gate_fixture", "code_version": "ci"},
        created_at=now - timedelta(days=3),
    )
    challenger = RankingModelVersion(
        name="release-gate-challenger",
        is_active=False,
        weights={"semantic_score": 0.40, "baseline_score": 0.30, "behavior_score": 0.30},
        metrics={
            "auc_default": 0.720,
            "auc_learned": 0.792,
            "auc_gain": 0.072,
            "auc_gain_test": 0.072,
            "precision_at_10": 0.74,
        },
        trained_window_start=now - timedelta(days=days),
        trained_window_end=now - timedelta(days=1),
        training_rows=5200,
        feature_schema={"semantic_score": "float", "baseline_score": "float", "behavior_score": "float"},
        serving_ready=True,
        lifecycle={"status": "approved", "promotion_reason": "ci challenger beats champion"},
        training_metadata={"source": "release_gate_fixture", "code_version": "ci"},
        created_at=now - timedelta(days=1),
    )
    await champion.insert()
    await challenger.insert()
    return champion, challenger


async def _seed_interactions(
    *,
    users: list[User],
    opportunities: list[Opportunity],
    champion: RankingModelVersion,
    challenger: RankingModelVersion,
    days: int,
    impressions_per_mode: int,
    requests_per_mode: int,
) -> dict[str, int]:
    interaction_targets = {
        "baseline": {"clicks": 36, "applies": 18, "model_id": str(champion.id), "score": 0.62},
        "semantic": {"clicks": 54, "applies": 30, "model_id": str(champion.id), "score": 0.72},
        "ml": {"clicks": 72, "applies": 42, "model_id": str(challenger.id), "score": 0.82},
    }
    interactions: list[OpportunityInteraction] = []
    telemetry: list[RankingRequestTelemetry] = []
    feature_rows: list[FeatureStoreRow] = []

    for mode, targets in interaction_targets.items():
        for index in range(impressions_per_mode):
            user = users[index % len(users)]
            opportunity = opportunities[index % len(opportunities)]
            created_at = _created_at(index, days=days)
            interactions.append(
                OpportunityInteraction(
                    user_id=user.id,
                    opportunity_id=opportunity.id,
                    interaction_type="impression",
                    ranking_mode=mode,  # type: ignore[arg-type]
                    experiment_key="release_gate_rollout",
                    experiment_variant=mode,
                    query=f"release gate {mode}",
                    model_version_id=str(targets["model_id"]),
                    rank_position=(index % 20) + 1,
                    match_score=float(targets["score"]),
                    features={
                        "semantic_score": float(targets["score"]),
                        "baseline_score": 0.56 + float(index % 5) / 100.0,
                        "behavior_score": 0.20 + float(index % 7) / 100.0,
                    },
                    traffic_type="real",
                    created_at=created_at,
                )
            )
            if index < int(targets["clicks"]):
                interactions.append(
                    OpportunityInteraction(
                        user_id=user.id,
                        opportunity_id=opportunity.id,
                        interaction_type="click",
                        ranking_mode=mode,  # type: ignore[arg-type]
                        experiment_key="release_gate_rollout",
                        experiment_variant=mode,
                        query=f"release gate {mode}",
                        model_version_id=str(targets["model_id"]),
                        rank_position=(index % 20) + 1,
                        match_score=float(targets["score"]),
                        traffic_type="real",
                        created_at=created_at + timedelta(seconds=3),
                    )
                )
            if index < int(targets["applies"]):
                interactions.append(
                    OpportunityInteraction(
                        user_id=user.id,
                        opportunity_id=opportunity.id,
                        interaction_type="apply",
                        ranking_mode=mode,  # type: ignore[arg-type]
                        experiment_key="release_gate_rollout",
                        experiment_variant=mode,
                        query=f"release gate {mode}",
                        model_version_id=str(targets["model_id"]),
                        rank_position=(index % 20) + 1,
                        match_score=float(targets["score"]),
                        traffic_type="real",
                        created_at=created_at + timedelta(seconds=8),
                    )
                )
            if index < 80:
                feature_rows.append(
                    FeatureStoreRow(
                        row_key=f"release-gate:{mode}:{index}",
                        date=utc_now().date().isoformat(),
                        user_id=str(user.id),
                        opportunity_id=str(opportunity.id),
                        ranking_mode=mode,
                        experiment_key="release_gate_rollout",
                        experiment_variant=mode,
                        traffic_type="real",
                        rank_position=(index % 20) + 1,
                        match_score=float(targets["score"]),
                        features={"semantic_score": float(targets["score"]), "behavior_score": 0.25},
                        labels={"clicked": index < int(targets["clicks"]), "applied": index < int(targets["applies"])},
                        source_event_id=f"release-gate:{mode}:{index}",
                        created_at=created_at,
                        updated_at=utc_now(),
                    )
                )

        latency_base = {"baseline": 130.0, "semantic": 112.0, "ml": 92.0}[mode]
        freshness_base = {"baseline": 72.0, "semantic": 54.0, "ml": 36.0}[mode]
        for index in range(requests_per_mode):
            user = users[index % len(users)]
            telemetry.append(
                RankingRequestTelemetry(
                    user_id=user.id,
                    request_kind="recommended",
                    requested_ranking_mode=mode,
                    ranking_mode=mode,
                    experiment_key="release_gate_rollout",
                    experiment_variant=mode,
                    rollout_variant=mode,
                    rollout_percent=100,
                    model_version_id=str(targets["model_id"]),
                    surface="ci_release_gate",
                    success=True,
                    latency_ms=latency_base + float(index % 5),
                    results_count=20,
                    freshness_seconds=freshness_base + float(index % 3),
                    traffic_type="real",
                    created_at=_created_at(index, days=days),
                )
            )

    for index in range(80):
        telemetry.append(
            RankingRequestTelemetry(
                user_id=users[index % len(users)].id,
                request_kind="assistant_chat",
                requested_ranking_mode=None,
                ranking_mode=None,
                surface="ci_release_gate_assistant",
                success=True,
                latency_ms=180.0 + float(index % 10),
                results_count=1,
                freshness_seconds=10.0,
                traffic_type="real",
                created_at=_created_at(index, days=days),
            )
        )

    await _insert_many(interactions)
    await _insert_many(telemetry)
    await _insert_many(feature_rows)
    return {
        "interactions": len(interactions),
        "ranking_request_telemetry": len(telemetry),
        "feature_store_rows": len(feature_rows),
    }


async def _seed_observability(*, champion: RankingModelVersion, days: int) -> dict[str, int]:
    now = utc_now()
    await ModelDriftReport(
        model_version_id=str(champion.id),
        window_start=now - timedelta(days=days),
        window_end=now,
        metrics={"query_bucket_psi": 0.012, "max_feature_mean_z": 0.22, "impressions": 900},
        alert=False,
        created_at=now,
    ).insert()
    audits = [
        AssistantAuditEvent(
            request_id=f"release-gate-assistant-{index}",
            route="recommendation",
            tool_name="recommend_opportunities",
            prompt_version="assistant.v2",
            latency_ms=180.0 + float(index % 10),
            success=True,
            citation_count=3,
            metadata={"hallucination_flag": False, "citation_correctness": 1.0, "source": "release_gate_fixture"},
            created_at=_created_at(index, days=days),
        )
        for index in range(80)
    ]
    await _insert_many(audits)
    await Experiment(
        key="release_gate_rollout",
        description="Release gate deterministic rollout fixture.",
        variants=[
            {"name": "baseline", "weight": 34.0, "is_control": True},
            {"name": "semantic", "weight": 33.0, "is_control": False},
            {"name": "ml", "weight": 33.0, "is_control": False},
        ],
        status="active",
        created_at=now - timedelta(days=days),
        updated_at=now,
    ).insert()
    return {"model_drift_reports": 1, "assistant_audit_events": len(audits), "experiments": 1}


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Seed deterministic high-volume data for release-blocking ML gates.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--impressions-per-mode", type=int, default=260)
    parser.add_argument("--requests-per-mode", type=int, default=140)
    parser.add_argument("--reset", action="store_true", help="Drop the configured fixture database before seeding.")
    parser.add_argument(
        "--allow-reset-non-ci",
        action="store_true",
        help="Allow --reset against a database name without a CI/test/fixture marker.",
    )
    args = parser.parse_args()

    db_name = settings.MONGODB_DB_NAME
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        if args.reset:
            if not args.allow_reset_non_ci and not _is_safe_fixture_db(db_name):
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "Refusing to reset a database without a CI/test/fixture marker.",
                            "database": db_name,
                        },
                        indent=2,
                    )
                )
                return 2
            await client.drop_database(db_name)

        await init_beanie(
            database=client[db_name],
            document_models=[
                AssistantAuditEvent,
                Experiment,
                FeatureStoreRow,
                ModelDriftReport,
                Opportunity,
                OpportunityInteraction,
                Profile,
                RankingModelVersion,
                RankingRequestTelemetry,
                User,
            ],
        )

        days = max(1, min(int(args.days), 90))
        impressions_per_mode = max(220, int(args.impressions_per_mode))
        requests_per_mode = max(120, int(args.requests_per_mode))
        users, opportunities = await _seed_users_and_opportunities(days=days)
        champion, challenger = await _seed_models(days=days)
        counts = {
            "users": len(users),
            "opportunities": len(opportunities),
            **await _seed_interactions(
                users=users,
                opportunities=opportunities,
                champion=champion,
                challenger=challenger,
                days=days,
                impressions_per_mode=impressions_per_mode,
                requests_per_mode=requests_per_mode,
            ),
            **await _seed_observability(champion=champion, days=days),
        }
        print(
            json.dumps(
                {
                    "status": "ok",
                    "database": db_name,
                    "days": days,
                    "impressions_per_mode": impressions_per_mode,
                    "requests_per_mode": requests_per_mode,
                    "counts": counts,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
