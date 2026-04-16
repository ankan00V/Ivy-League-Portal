from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from beanie import init_beanie
from beanie.odm.operators.find.comparison import In
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.user import User
from app.services.personalization.feature_builder import build_ranker_features, skills_overlap_score
from app.services.recommendation_service import recommendation_service


@dataclass(frozen=True)
class Row:
    user_id: str
    opportunity_id: str
    label: float
    features: dict[str, float]


async def _init_db() -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URL, tls=True, tlsAllowInvalidCertificates=True)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Profile,
            Opportunity,
            OpportunityInteraction,
            Application,
        ],
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


async def _load_interactions(*, since: datetime) -> list[OpportunityInteraction]:
    return await OpportunityInteraction.find_many(OpportunityInteraction.created_at >= since).to_list()


def _label_from_events(events: Iterable[OpportunityInteraction]) -> float:
    # Relevance levels for ranking:
    # apply > save > click/view > impression
    best = 0.0
    for event in events:
        if event.interaction_type == "apply":
            best = max(best, 3.0)
        elif event.interaction_type == "save":
            best = max(best, 2.0)
        elif event.interaction_type in {"click", "view"}:
            best = max(best, 1.0)
    return best


async def _build_training_rows(
    *,
    lookback_days: int,
    label_window_hours: int,
    max_users: int | None,
    max_impressions: int | None,
) -> list[Row]:
    since = _now() - timedelta(days=max(1, lookback_days))
    interactions = await _load_interactions(since=since)

    # Index by (user, opp) and keep impression timestamps.
    impressions: list[OpportunityInteraction] = [e for e in interactions if e.interaction_type == "impression"]
    if max_impressions is not None:
        impressions = impressions[: max(0, int(max_impressions))]

    # Candidate users.
    user_ids = sorted({str(e.user_id) for e in impressions})
    if max_users is not None:
        user_ids = user_ids[: max(0, int(max_users))]
    user_id_set = set(user_ids)

    # Group all non-impressions by (user_id, opportunity_id) for quick labeling.
    event_map: dict[tuple[str, str], list[OpportunityInteraction]] = {}
    for e in interactions:
        if e.interaction_type == "impression":
            continue
        key = (str(e.user_id), str(e.opportunity_id))
        event_map.setdefault(key, []).append(e)

    # Fetch profiles + opportunities.
    profile_ids = [e.user_id for e in impressions if str(e.user_id) in user_id_set]
    profiles = await Profile.find_many(In(Profile.user_id, profile_ids)).to_list()
    profile_by_user = {str(p.user_id): p for p in profiles}

    opp_ids = sorted({e.opportunity_id for e in impressions if str(e.user_id) in user_id_set})
    opportunities = await Opportunity.find_many(In(Opportunity.id, opp_ids)).to_list()
    opp_by_id = {str(o.id): o for o in opportunities}

    # Precompute behavior maps per user (interaction history feature).
    behavior_by_user: dict[str, dict[str, dict[str, float]]] = {}
    for user_id in user_ids:
        try:
            behavior_by_user[user_id] = await recommendation_service._build_behavior_map(user_id)  # type: ignore[attr-defined]
        except Exception:
            behavior_by_user[user_id] = {"domain": {}, "type": {}}

    rows: list[Row] = []
    label_window = timedelta(hours=max(1, label_window_hours))

    for imp in impressions:
        user_id = str(imp.user_id)
        if user_id not in user_id_set:
            continue
        opportunity_id = str(imp.opportunity_id)
        opportunity = opp_by_id.get(opportunity_id)
        profile = profile_by_user.get(user_id)
        if not opportunity or not profile:
            continue

        # Collect events within window after this impression.
        window_end = imp.created_at + label_window
        candidates = [
            e for e in event_map.get((user_id, opportunity_id), [])
            if imp.created_at <= e.created_at <= window_end
        ]
        label = _label_from_events(candidates)

        stored = imp.features or {}
        baseline_score = _as_float(stored.get("baseline_score"))
        semantic_score = _as_float(stored.get("semantic_score"))
        behavior_score = _as_float(stored.get("behavior_score"))

        # If impression didn't carry scores (older rows), recompute a subset.
        if baseline_score <= 0 and semantic_score <= 0:
            baseline_score, _reasons = __import__("app.services.intelligence", fromlist=["score_opportunity_match"]).score_opportunity_match(profile, opportunity)  # type: ignore[attr-defined]

        behavior_map = behavior_by_user.get(user_id) or {"domain": {}, "type": {}}
        behavior_domain_pref, behavior_type_pref = recommendation_service._behavior_prefs(opportunity, behavior_map)  # type: ignore[attr-defined]
        overlap = skills_overlap_score(profile=profile, opportunity=opportunity)

        feats = build_ranker_features(
            profile=profile,
            opportunity=opportunity,
            semantic_score=semantic_score,
            skills_overlap_score=overlap,
            baseline_score=baseline_score,
            behavior_score=behavior_score,
            behavior_domain_pref=behavior_domain_pref,
            behavior_type_pref=behavior_type_pref,
        ).values

        rows.append(Row(user_id=user_id, opportunity_id=opportunity_id, label=label, features=feats))

    return rows


def _group_by_user(rows: list[Row]) -> tuple[list[Row], list[int]]:
    rows_sorted = sorted(rows, key=lambda r: r.user_id)
    groups: list[int] = []
    if not rows_sorted:
        return rows_sorted, groups
    current = rows_sorted[0].user_id
    count = 0
    for row in rows_sorted:
        if row.user_id != current:
            groups.append(count)
            current = row.user_id
            count = 0
        count += 1
    groups.append(count)
    return rows_sorted, groups


def _train_lightgbm_ranker(
    *,
    rows: list[Row],
    output_path: Path,
    valid_fraction: float = 0.2,
) -> dict[str, Any]:
    import lightgbm as lgb  # type: ignore

    rows, groups = _group_by_user(rows)
    if not rows or not groups:
        raise ValueError("no_rows")

    feature_names = sorted(rows[0].features.keys())
    X = np.asarray([[r.features.get(name, 0.0) for name in feature_names] for r in rows], dtype=float)
    y = np.asarray([r.label for r in rows], dtype=float)

    # Split by user groups to avoid leakage.
    group_count = len(groups)
    valid_groups = max(1, int(round(group_count * max(0.0, min(valid_fraction, 0.8)))))
    train_groups = groups[: group_count - valid_groups]
    valid_groups_list = groups[group_count - valid_groups :]

    train_n = int(sum(train_groups))
    X_train, y_train = X[:train_n], y[:train_n]
    X_valid, y_valid = X[train_n:], y[train_n:]

    dtrain = lgb.Dataset(X_train, label=y_train, group=train_groups, feature_name=feature_names)
    dvalid = lgb.Dataset(X_valid, label=y_valid, group=valid_groups_list, feature_name=feature_names, reference=dtrain)

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [1, 3, 5, 10],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "verbosity": -1,
        "seed": 42,
    }

    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=500,
        valid_sets=[dvalid],
        valid_names=["valid"],
        callbacks=[lgb.early_stopping(stopping_rounds=30)],
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(output_path))

    return {
        "model": "lightgbm",
        "rows": len(rows),
        "groups": len(groups),
        "features": feature_names,
        "best_iteration": int(getattr(booster, "best_iteration", 0) or 0),
        "output_path": str(output_path),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Train a LightGBM learned ranker from interaction logs.")
    parser.add_argument("--lookback-days", type=int, default=int(settings.MLOPS_RETRAIN_LOOKBACK_DAYS))
    parser.add_argument("--label-window-hours", type=int, default=int(settings.MLOPS_LABEL_WINDOW_HOURS))
    parser.add_argument("--max-users", type=int, default=0)
    parser.add_argument("--max-impressions", type=int, default=0)
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path("backend/models/learned_ranker.lgb.txt")),
        help="Model output path (LightGBM Booster.save_model format).",
    )
    args = parser.parse_args()

    await _init_db()

    rows = await _build_training_rows(
        lookback_days=int(args.lookback_days),
        label_window_hours=int(args.label_window_hours),
        max_users=None if int(args.max_users) <= 0 else int(args.max_users),
        max_impressions=None if int(args.max_impressions) <= 0 else int(args.max_impressions),
    )
    if len(rows) < max(1, int(settings.MLOPS_MIN_TRAINING_ROWS)):
        raise SystemExit(f"Not enough rows to train: {len(rows)} < {settings.MLOPS_MIN_TRAINING_ROWS}")

    report = _train_lightgbm_ranker(rows=rows, output_path=Path(args.output))
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
