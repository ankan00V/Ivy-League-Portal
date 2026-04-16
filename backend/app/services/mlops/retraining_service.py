from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

import numpy as np
from beanie.odm.operators.find.comparison import In

from app.core.config import settings
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.services.ranking_model_service import DEFAULT_RANKING_WEIGHTS, ranking_model_service


def _bucket_query(query: Optional[str], buckets: int) -> int:
    value = (query or "").strip().lower()
    digest = md5(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(1, int(buckets))


def _roc_auc_score(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if y_true.size == 0:
        return 0.0

    positives = int((y_true == 1).sum())
    negatives = int((y_true == 0).sum())
    if positives == 0 or negatives == 0:
        return 0.0

    order = np.argsort(y_score)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, y_true.size + 1, dtype=np.float64)
    sum_ranks_pos = float(ranks[y_true == 1].sum())

    # Mann–Whitney U statistic to AUC.
    auc = (sum_ranks_pos - (positives * (positives + 1) / 2.0)) / float(positives * negatives)
    return float(max(0.0, min(1.0, auc)))


def _feature_stats(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"count": 0}
    return {
        "count": float(values.size),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "min": float(values.min()),
        "max": float(values.max()),
        "p10": float(np.percentile(values, 10)),
        "p50": float(np.percentile(values, 50)),
        "p90": float(np.percentile(values, 90)),
    }


@dataclass(frozen=True)
class TrainingResult:
    weights: dict[str, float]
    metrics: dict[str, float]
    baselines: dict[str, Any]
    training_rows: int
    window_start: datetime
    window_end: datetime
    auto_activated: bool
    activation_reason: str


class RetrainingService:
    async def build_training_set(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        label_window_hours: int,
        query_buckets: int = 128,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        label_window = timedelta(hours=max(1, int(label_window_hours)))

        impressions = await OpportunityInteraction.find_many(
            OpportunityInteraction.interaction_type == "impression",
            OpportunityInteraction.created_at >= window_start,
            OpportunityInteraction.created_at <= window_end,
        ).to_list()
        impressions = [item for item in impressions if isinstance(item.features, dict)]

        positives = await OpportunityInteraction.find_many(
            In(OpportunityInteraction.interaction_type, ["click", "apply"]),
            OpportunityInteraction.created_at >= window_start,
            OpportunityInteraction.created_at <= (window_end + label_window),
        ).to_list()

        positive_map: dict[tuple[str, str], list[datetime]] = {}
        for interaction in positives:
            key = (str(interaction.user_id), str(interaction.opportunity_id))
            positive_map.setdefault(key, []).append(interaction.created_at)
        for times in positive_map.values():
            times.sort()

        rows: list[list[float]] = []
        labels: list[int] = []

        query_bucket_counts = np.zeros((max(1, int(query_buckets)),), dtype=np.int64)
        query_lengths: list[int] = []

        for imp in impressions:
            feats: dict[str, Any] = imp.features or {}
            baseline = float(feats.get("baseline_score") or 0.0)
            semantic = float(feats.get("semantic_score") or 0.0)
            behavior = float(feats.get("behavior_score") or 0.0)

            # Scale scores from [0..100] -> [0..1] to stabilize.
            rows.append([semantic / 100.0, baseline / 100.0, behavior / 100.0])

            key = (str(imp.user_id), str(imp.opportunity_id))
            times = positive_map.get(key)
            label = 0
            if times:
                left = bisect_left(times, imp.created_at)
                if left < len(times) and times[left] <= (imp.created_at + label_window):
                    label = 1
            labels.append(label)

            q = (imp.query or "").strip()
            query_lengths.append(len(q))
            query_bucket_counts[_bucket_query(q, query_buckets)] += 1

        X = np.asarray(rows, dtype=np.float64)
        y = np.asarray(labels, dtype=np.int64)

        total_queries = int(query_bucket_counts.sum())
        query_bucket_dist = (
            (query_bucket_counts / float(total_queries)).astype(np.float64) if total_queries > 0 else query_bucket_counts
        )
        baselines: dict[str, Any] = {
            "query_buckets": {
                "buckets": int(query_buckets),
                "dist": [float(v) for v in query_bucket_dist.tolist()],
            },
            "query_length": _feature_stats(np.asarray(query_lengths, dtype=np.float64)),
            "features": {
                "semantic_score": _feature_stats(X[:, 0] if X.size else np.asarray([], dtype=np.float64)),
                "baseline_score": _feature_stats(X[:, 1] if X.size else np.asarray([], dtype=np.float64)),
                "behavior_score": _feature_stats(X[:, 2] if X.size else np.asarray([], dtype=np.float64)),
            },
        }

        return X, y, baselines

    def train_weights(
        self,
        *,
        X: np.ndarray,
        y: np.ndarray,
        grid_step: float = 0.05,
        seed: int = 42,
    ) -> dict[str, float] | None:
        if X.size == 0 or y.size == 0 or X.shape[0] != y.shape[0]:
            return None

        n = X.shape[0]
        rng = np.random.default_rng(int(seed))
        order = rng.permutation(n)
        split = max(1, int(n * 0.8))

        train_idx = order[:split]
        val_idx = order[split:]
        if val_idx.size == 0:
            val_idx = train_idx

        X_val = X[val_idx]
        y_val = y[val_idx]

        step = float(max(0.01, min(0.25, grid_step)))

        best_auc = -1.0
        best_weights: dict[str, float] | None = None

        # Grid search on simplex w_sem + w_base + w_beh = 1, with non-negative weights.
        grid = np.arange(0.0, 1.0 + (step / 2.0), step)
        for w_sem in grid:
            for w_base in grid:
                w_beh = 1.0 - (w_sem + w_base)
                if w_beh < 0.0:
                    continue
                w = np.asarray([w_sem, w_base, w_beh], dtype=np.float64)
                scores = X_val @ w
                auc = _roc_auc_score(y_val, scores)
                if auc > best_auc:
                    best_auc = auc
                    best_weights = {"semantic": float(w_sem), "baseline": float(w_base), "behavior": float(w_beh)}

        if not best_weights:
            return None

        # Normalize (avoid float drift from subtraction).
        total = best_weights["semantic"] + best_weights["baseline"] + best_weights["behavior"]
        if total <= 0:
            return dict(DEFAULT_RANKING_WEIGHTS)
        return {k: float(v) / float(total) for k, v in best_weights.items()}

    async def retrain_and_register(
        self,
        *,
        lookback_days: int = 90,
        label_window_hours: int = 72,
        min_rows: int = 200,
        grid_step: float = 0.05,
        auto_activate: bool = False,
        min_auc_gain_for_activation: float = float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN),
        notes: Optional[str] = None,
    ) -> TrainingResult:
        window_end = datetime.utcnow()
        window_start = window_end - timedelta(days=max(1, int(lookback_days)))

        X, y, baselines = await self.build_training_set(
            window_start=window_start,
            window_end=window_end,
            label_window_hours=label_window_hours,
        )

        training_rows = int(X.shape[0])
        if training_rows < int(min_rows):
            raise ValueError(f"insufficient_training_data: {training_rows} < {int(min_rows)}")

        active = await ranking_model_service.get_active(cache_ttl_seconds=0)
        baseline_weights = active.weights if active.model_version_id else dict(DEFAULT_RANKING_WEIGHTS)

        default_w = np.asarray(
            [baseline_weights["semantic"], baseline_weights["baseline"], baseline_weights["behavior"]],
            dtype=np.float64,
        )
        default_w = default_w / float(default_w.sum() or 1.0)

        learned = self.train_weights(X=X, y=y, grid_step=grid_step)
        if not learned:
            raise ValueError("training_failed")

        learned_w = np.asarray([learned["semantic"], learned["baseline"], learned["behavior"]], dtype=np.float64)

        auc_default = _roc_auc_score(y, X @ default_w)
        auc_learned = _roc_auc_score(y, X @ learned_w)
        auc_gain = float(auc_learned - auc_default)
        positive_rate = float((y == 1).sum() / float(max(1, y.size)))

        metrics = {
            "auc_default": float(round(auc_default, 6)),
            "auc_learned": float(round(auc_learned, 6)),
            "auc_gain": float(round(auc_gain, 6)),
            "positive_rate": float(round(positive_rate, 6)),
            "rows": float(training_rows),
            "grid_step": float(grid_step),
        }

        version = RankingModelVersion(
            name="ranking-weights-v1",
            is_active=False,
            weights=learned,
            metrics=metrics,
            baselines=baselines,
            trained_window_start=window_start,
            trained_window_end=window_end,
            training_rows=training_rows,
            label_window_hours=int(label_window_hours),
            notes=notes,
        )
        await version.insert()

        safe_min_gain = float(min_auc_gain_for_activation)
        should_activate = bool(auto_activate) and (auc_gain >= safe_min_gain)
        activation_reason = "auto_activate_disabled"
        if auto_activate and not should_activate:
            activation_reason = f"auc_gain_below_threshold:{auc_gain:.6f}<{safe_min_gain:.6f}"
        elif should_activate:
            await ranking_model_service.activate(model_id=str(version.id))
            activation_reason = "activated"

        metrics["auto_activated"] = 1.0 if should_activate else 0.0

        return TrainingResult(
            weights=learned,
            metrics=metrics,
            baselines=baselines,
            training_rows=training_rows,
            window_start=window_start,
            window_end=window_end,
            auto_activated=bool(should_activate),
            activation_reason=activation_reason,
        )


retraining_service = RetrainingService()
