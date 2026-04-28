from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.core.time import utc_now
from app.models.ranking_model_version import RankingModelVersion
from app.services.model_artifact_service import model_artifact_service


DEFAULT_RANKING_WEIGHTS: dict[str, float] = {
    "semantic": 0.55,
    "baseline": 0.30,
    "behavior": 0.15,
}


@dataclass(frozen=True)
class ActiveRankingModel:
    model_version_id: Optional[str]
    weights: dict[str, float]


_cache: ActiveRankingModel | None = None
_cache_until: datetime | None = None


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    semantic = float(weights.get("semantic", DEFAULT_RANKING_WEIGHTS["semantic"]))
    baseline = float(weights.get("baseline", DEFAULT_RANKING_WEIGHTS["baseline"]))
    behavior = float(weights.get("behavior", DEFAULT_RANKING_WEIGHTS["behavior"]))

    semantic = max(0.0, semantic)
    baseline = max(0.0, baseline)
    behavior = max(0.0, behavior)

    total = semantic + baseline + behavior
    if total <= 0:
        return dict(DEFAULT_RANKING_WEIGHTS)

    return {
        "semantic": semantic / total,
        "baseline": baseline / total,
        "behavior": behavior / total,
    }


class RankingModelService:
    async def get_active(self, *, cache_ttl_seconds: int = 60) -> ActiveRankingModel:
        global _cache, _cache_until

        now = utc_now()
        if _cache is not None and _cache_until is not None and now <= _cache_until:
            return _cache

        active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
        if not active:
            result = ActiveRankingModel(model_version_id=None, weights=dict(DEFAULT_RANKING_WEIGHTS))
            _cache = result
            _cache_until = now + timedelta(seconds=max(0, int(cache_ttl_seconds)))
            return result

        result = ActiveRankingModel(
            model_version_id=str(active.id),
            weights=_normalize_weights(active.weights or {}),
        )
        _cache = result
        _cache_until = now + timedelta(seconds=max(0, int(cache_ttl_seconds)))
        return result

    async def activate(self, *, model_id: str) -> RankingModelVersion:
        # Deactivate any currently-active models (normally 0/1).
        active_models = await RankingModelVersion.find_many(RankingModelVersion.is_active == True).to_list()  # noqa: E712
        previous_active = active_models[0] if active_models else None
        for model in active_models:
            model.is_active = False
            await model.save()

        model = await RankingModelVersion.get(model_id)
        if not model:
            raise ValueError("model_not_found")
        if str(model.artifact_uri or "").strip():
            model_artifact_service.ensure_model_version_artifact_ready(model)

        model.is_active = True
        lifecycle = dict(model.lifecycle or {})
        if previous_active is not None and str(previous_active.id) != str(model.id):
            lifecycle["previous_active_model_id"] = str(previous_active.id)
            lifecycle["previous_active_model_name"] = str(previous_active.name or "")
        lifecycle["activated_at"] = utc_now().isoformat()
        model.lifecycle = lifecycle
        await model.save()

        # Invalidate cache.
        global _cache, _cache_until
        _cache = None
        _cache_until = None

        return model

    async def rollback(self, *, model_id: str | None = None) -> RankingModelVersion:
        if model_id:
            return await self.activate(model_id=model_id)

        active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
        if not active:
            raise ValueError("active_model_not_found")

        previous_model_id = str((active.lifecycle or {}).get("previous_active_model_id") or "").strip()
        if not previous_model_id:
            raise ValueError("rollback_target_not_found")

        return await self.activate(model_id=previous_model_id)

    async def deactivate_all(self) -> int:
        active_models = await RankingModelVersion.find_many(RankingModelVersion.is_active == True).to_list()  # noqa: E712
        for model in active_models:
            model.is_active = False
            await model.save()

        global _cache, _cache_until
        _cache = None
        _cache_until = None

        return len(active_models)

    async def ensure_active_model(
        self,
        *,
        bootstrap_name: str = "ranking-weights-bootstrap-v1",
        notes: str = "Auto-bootstrapped default ranking weights.",
    ) -> ActiveRankingModel:
        """
        Ensure there is exactly one active model reference for observability + governance.

        Behavior:
        1) If an active model exists, return it.
        2) Else if any model versions exist, activate the newest one.
        3) Else create and activate a bootstrap default model row.
        """
        global _cache, _cache_until

        active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
        if active:
            result = ActiveRankingModel(
                model_version_id=str(active.id),
                weights=_normalize_weights(active.weights or {}),
            )
            _cache = result
            _cache_until = utc_now() + timedelta(seconds=60)
            return result

        latest = await RankingModelVersion.find_many().sort("-created_at").limit(1).to_list()
        if latest:
            await self.activate(model_id=str(latest[0].id))
            return await self.get_active(cache_ttl_seconds=0)

        bootstrap = RankingModelVersion(
            name=bootstrap_name,
            is_active=True,
            weights=dict(DEFAULT_RANKING_WEIGHTS),
            metrics={
                "auc_default": 0.0,
                "auc_learned": 0.0,
                "positive_rate": 0.0,
                "rows": 0.0,
            },
            training_rows=0,
            label_window_hours=72,
            notes=notes,
        )
        await bootstrap.insert()

        result = ActiveRankingModel(
            model_version_id=str(bootstrap.id),
            weights=_normalize_weights(bootstrap.weights or {}),
        )
        _cache = result
        _cache_until = utc_now() + timedelta(seconds=60)
        return result


ranking_model_service = RankingModelService()
