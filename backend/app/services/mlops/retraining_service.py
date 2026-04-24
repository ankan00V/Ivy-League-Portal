from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

import numpy as np
from beanie.odm.operators.find.comparison import In

from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.services.mlops.activation_policy import evaluate_activation_policy
from app.services.mlops.rollout_guardrail_service import rollout_guardrail_service
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

    auc = (sum_ranks_pos - (positives * (positives + 1) / 2.0)) / float(positives * negatives)
    return float(max(0.0, min(1.0, auc)))


def _feature_stats(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"count": 0.0}
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
class TrainingExample:
    user_id: str
    created_at: datetime
    query: str
    features: tuple[float, float, float]
    label: int


@dataclass(frozen=True)
class TrainingSplits:
    strategy: str
    train_idx: np.ndarray
    validation_idx: np.ndarray
    test_idx: np.ndarray
    summary: dict[str, Any]


@dataclass(frozen=True)
class TrainingResult:
    weights: dict[str, float]
    metrics: dict[str, float]
    baselines: dict[str, Any]
    lifecycle: dict[str, Any]
    training_rows: int
    window_start: datetime
    window_end: datetime
    auto_activated: bool
    activation_reason: str
    split_strategy: str
    training_metadata: dict[str, Any]
    model_card: dict[str, Any]


class RetrainingService:
    async def build_training_examples(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        label_window_hours: int,
        query_buckets: int = 128,
    ) -> tuple[list[TrainingExample], dict[str, Any]]:
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

        examples: list[TrainingExample] = []
        query_bucket_counts = np.zeros((max(1, int(query_buckets)),), dtype=np.int64)
        query_lengths: list[int] = []

        for imp in impressions:
            feats: dict[str, Any] = imp.features or {}
            baseline = float(feats.get("baseline_score") or 0.0)
            semantic = float(feats.get("semantic_score") or 0.0)
            behavior = float(feats.get("behavior_score") or 0.0)

            key = (str(imp.user_id), str(imp.opportunity_id))
            times = positive_map.get(key)
            label = 0
            if times:
                left = bisect_left(times, imp.created_at)
                if left < len(times) and times[left] <= (imp.created_at + label_window):
                    label = 1

            query_value = (imp.query or "").strip()
            examples.append(
                TrainingExample(
                    user_id=str(imp.user_id),
                    created_at=imp.created_at,
                    query=query_value,
                    features=(semantic / 100.0, baseline / 100.0, behavior / 100.0),
                    label=label,
                )
            )
            query_lengths.append(len(query_value))
            query_bucket_counts[_bucket_query(query_value, query_buckets)] += 1

        X = self._feature_matrix(examples)
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
        return examples, baselines

    async def build_training_set(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        label_window_hours: int,
        query_buckets: int = 128,
    ) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
        examples, baselines = await self.build_training_examples(
            window_start=window_start,
            window_end=window_end,
            label_window_hours=label_window_hours,
            query_buckets=query_buckets,
        )
        return self._feature_matrix(examples), self._label_vector(examples), baselines

    def _feature_matrix(self, examples: list[TrainingExample]) -> np.ndarray:
        rows = [list(example.features) for example in examples]
        if not rows:
            return np.empty((0, 3), dtype=np.float64)
        return np.asarray(rows, dtype=np.float64)

    def _label_vector(self, examples: list[TrainingExample]) -> np.ndarray:
        return np.asarray([example.label for example in examples], dtype=np.int64)

    def _split_examples(self, examples: list[TrainingExample]) -> TrainingSplits:
        if not examples:
            empty = np.asarray([], dtype=np.int64)
            return TrainingSplits(
                strategy="time",
                train_idx=empty,
                validation_idx=empty,
                test_idx=empty,
                summary={"counts": {"train": 0, "validation": 0, "test": 0}},
            )

        indexed = list(enumerate(examples))
        indexed.sort(key=lambda row: (row[1].created_at, row[0]))
        ordered_indices = np.asarray([row[0] for row in indexed], dtype=np.int64)
        n = int(ordered_indices.size)

        train_end = max(1, int(round(n * 0.6)))
        validation_end = max(train_end + 1, int(round(n * 0.8)))
        validation_end = min(validation_end, max(train_end + 1, n - 1))

        time_splits = self._make_split_payload(
            strategy="time",
            examples=examples,
            train_idx=ordered_indices[:train_end],
            validation_idx=ordered_indices[train_end:validation_end],
            test_idx=ordered_indices[validation_end:],
        )
        if self._split_has_classes(time_splits, examples):
            return time_splits

        bucketed: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
        for idx, example in enumerate(examples):
            digest = md5(example.user_id.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % 10
            if bucket < 6:
                bucketed["train"].append(idx)
            elif bucket < 8:
                bucketed["validation"].append(idx)
            else:
                bucketed["test"].append(idx)

        user_splits = self._make_split_payload(
            strategy="user_hash",
            examples=examples,
            train_idx=np.asarray(bucketed["train"], dtype=np.int64),
            validation_idx=np.asarray(bucketed["validation"], dtype=np.int64),
            test_idx=np.asarray(bucketed["test"], dtype=np.int64),
        )
        if self._split_has_classes(user_splits, examples):
            return user_splits
        return time_splits

    def _split_has_classes(self, splits: TrainingSplits, examples: list[TrainingExample]) -> bool:
        labels = self._label_vector(examples)
        for idx in (splits.train_idx, splits.validation_idx, splits.test_idx):
            if idx.size == 0:
                return False
            split_labels = labels[idx]
            if int((split_labels == 1).sum()) == 0 or int((split_labels == 0).sum()) == 0:
                return False
        return True

    def _make_split_payload(
        self,
        *,
        strategy: str,
        examples: list[TrainingExample],
        train_idx: np.ndarray,
        validation_idx: np.ndarray,
        test_idx: np.ndarray,
    ) -> TrainingSplits:
        def _summarize(idx: np.ndarray) -> dict[str, Any]:
            if idx.size == 0:
                return {
                    "rows": 0,
                    "positive_rate": 0.0,
                    "users": 0,
                    "start": None,
                    "end": None,
                }
            subset = [examples[int(i)] for i in idx.tolist()]
            labels = np.asarray([example.label for example in subset], dtype=np.float64)
            created = [example.created_at for example in subset]
            return {
                "rows": int(idx.size),
                "positive_rate": float(labels.mean()) if labels.size else 0.0,
                "users": len({example.user_id for example in subset}),
                "start": min(created).isoformat(),
                "end": max(created).isoformat(),
            }

        return TrainingSplits(
            strategy=strategy,
            train_idx=train_idx,
            validation_idx=validation_idx,
            test_idx=test_idx,
            summary={
                "strategy": strategy,
                "counts": {
                    "train": _summarize(train_idx),
                    "validation": _summarize(validation_idx),
                    "test": _summarize(test_idx),
                },
            },
        )

    def train_weights(
        self,
        *,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_validation: Optional[np.ndarray] = None,
        y_validation: Optional[np.ndarray] = None,
        grid_step: float = 0.05,
    ) -> dict[str, float] | None:
        if X_train.size == 0 or y_train.size == 0 or X_train.shape[0] != y_train.shape[0]:
            return None

        def _has_binary_classes(values: Optional[np.ndarray]) -> bool:
            if values is None or values.size == 0:
                return False
            positives = int((values == 1).sum())
            negatives = int((values == 0).sum())
            return positives > 0 and negatives > 0

        use_validation = (
            X_validation is not None
            and y_validation is not None
            and X_validation.size > 0
            and y_validation.size > 0
            and X_validation.shape[0] == y_validation.shape[0]
            and _has_binary_classes(y_validation)
        )
        eval_X = X_validation if use_validation and X_validation is not None else X_train
        eval_y = y_validation if use_validation and y_validation is not None else y_train

        step = float(max(0.01, min(0.25, grid_step)))
        best_auc = -1.0
        best_weights: dict[str, float] | None = None
        grid = np.arange(0.0, 1.0 + (step / 2.0), step)
        for w_sem in grid:
            for w_base in grid:
                w_beh = 1.0 - (w_sem + w_base)
                if w_beh < 0.0:
                    continue
                w = np.asarray([w_sem, w_base, w_beh], dtype=np.float64)
                scores = eval_X @ w
                auc = _roc_auc_score(eval_y, scores)
                if auc > best_auc:
                    best_auc = auc
                    best_weights = {"semantic": float(w_sem), "baseline": float(w_base), "behavior": float(w_beh)}

        if not best_weights:
            return None

        total = best_weights["semantic"] + best_weights["baseline"] + best_weights["behavior"]
        if total <= 0:
            return dict(DEFAULT_RANKING_WEIGHTS)
        return {key: float(value) / float(total) for key, value in best_weights.items()}

    def _auc_by_split(
        self,
        *,
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray,
        splits: TrainingSplits,
    ) -> dict[str, float]:
        mapping = {
            "train": splits.train_idx,
            "validation": splits.validation_idx,
            "test": splits.test_idx,
        }
        payload: dict[str, float] = {}
        for name, idx in mapping.items():
            if idx.size == 0:
                payload[name] = 0.0
                continue
            payload[name] = _roc_auc_score(y[idx], X[idx] @ weights)
        return payload

    async def _latest_drift_snapshot(self) -> dict[str, Any]:
        latest = await ModelDriftReport.find_many().sort("-created_at").limit(1).to_list()
        if not latest:
            return {}
        item = latest[0]
        return {
            "id": str(item.id),
            "model_version_id": item.model_version_id,
            "created_at": item.created_at.isoformat(),
            "alert": bool(item.alert),
            "metrics": dict(item.metrics or {}),
        }

    def _build_training_metadata(
        self,
        *,
        splits: TrainingSplits,
        window_start: datetime,
        window_end: datetime,
        label_window_hours: int,
        grid_step: float,
        baselines: dict[str, Any],
        rows: int,
    ) -> dict[str, Any]:
        return {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "label_window_hours": int(label_window_hours),
            "rows": int(rows),
            "split_strategy": splits.strategy,
            "split_summary": splits.summary,
            "feature_names": ["semantic_score", "baseline_score", "behavior_score"],
            "selection_metric": "validation_auc_preferred",
            "feature_stats": dict(baselines.get("features") or {}),
            "query_stats": {
                "length": dict(baselines.get("query_length") or {}),
                "buckets": dict(baselines.get("query_buckets") or {}),
            },
            "grid_step": float(grid_step),
            "training_code": "ranking-weights-grid-search-v2",
        }

    def _build_model_card(
        self,
        *,
        metrics: dict[str, float],
        baselines: dict[str, Any],
        lifecycle: dict[str, Any],
        training_metadata: dict[str, Any],
        drift_snapshot: dict[str, Any],
        weights: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "model_type": "heuristic_weighted_ranker",
            "weights": dict(weights),
            "data_window": {
                "window_start": training_metadata.get("window_start"),
                "window_end": training_metadata.get("window_end"),
                "label_window_hours": training_metadata.get("label_window_hours"),
                "rows": training_metadata.get("rows"),
                "split_strategy": training_metadata.get("split_strategy"),
            },
            "feature_stats": dict(baselines.get("features") or {}),
            "query_stats": {
                "length": dict(baselines.get("query_length") or {}),
                "buckets": dict(baselines.get("query_buckets") or {}),
            },
            "auc": {
                "train": {
                    "default": metrics.get("auc_default_train", 0.0),
                    "learned": metrics.get("auc_learned_train", 0.0),
                    "gain": metrics.get("auc_gain_train", 0.0),
                },
                "validation": {
                    "default": metrics.get("auc_default_validation", 0.0),
                    "learned": metrics.get("auc_learned_validation", 0.0),
                    "gain": metrics.get("auc_gain_validation", 0.0),
                },
                "test": {
                    "default": metrics.get("auc_default_test", 0.0),
                    "learned": metrics.get("auc_learned_test", 0.0),
                    "gain": metrics.get("auc_gain_test", 0.0),
                },
            },
            "drift": drift_snapshot,
            "activation": {
                "activated": bool(lifecycle.get("activated")),
                "reason": lifecycle.get("activation_reason"),
                "policy": lifecycle.get("activation_policy"),
                "guardrails": dict((lifecycle.get("diagnostics") or {}).get("guardrails") or {}),
            },
            "reproducibility": training_metadata,
        }

    async def retrain_and_register(
        self,
        *,
        lookback_days: int = 90,
        label_window_hours: int = 72,
        min_rows: int = 200,
        grid_step: float = 0.05,
        auto_activate: bool = False,
        activation_policy: str = settings.MLOPS_ACTIVATION_POLICY,
        min_auc_gain_for_activation: float = float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN),
        min_positive_rate_for_activation: float = float(settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE),
        max_weight_shift_for_activation: float = float(settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT),
        notes: Optional[str] = None,
    ) -> TrainingResult:
        window_end = datetime.utcnow()
        window_start = window_end - timedelta(days=max(1, int(lookback_days)))

        examples, baselines = await self.build_training_examples(
            window_start=window_start,
            window_end=window_end,
            label_window_hours=label_window_hours,
        )
        X = self._feature_matrix(examples)
        y = self._label_vector(examples)
        training_rows = int(X.shape[0])
        if training_rows < int(min_rows):
            raise ValueError(f"insufficient_training_data: {training_rows} < {int(min_rows)}")

        splits = self._split_examples(examples)
        active = await ranking_model_service.get_active(cache_ttl_seconds=0)
        baseline_weights = active.weights if active.model_version_id else dict(DEFAULT_RANKING_WEIGHTS)
        default_w = np.asarray(
            [baseline_weights["semantic"], baseline_weights["baseline"], baseline_weights["behavior"]],
            dtype=np.float64,
        )
        default_w = default_w / float(default_w.sum() or 1.0)

        learned = self.train_weights(
            X_train=X[splits.train_idx],
            y_train=y[splits.train_idx],
            X_validation=X[splits.validation_idx],
            y_validation=y[splits.validation_idx],
            grid_step=grid_step,
        )
        if not learned:
            raise ValueError("training_failed")

        learned_w = np.asarray([learned["semantic"], learned["baseline"], learned["behavior"]], dtype=np.float64)
        auc_default_by_split = self._auc_by_split(X=X, y=y, weights=default_w, splits=splits)
        auc_learned_by_split = self._auc_by_split(X=X, y=y, weights=learned_w, splits=splits)
        auc_gain_by_split = {
            key: float(auc_learned_by_split.get(key, 0.0) - auc_default_by_split.get(key, 0.0))
            for key in ("train", "validation", "test")
        }
        positive_rate = float((y == 1).sum() / float(max(1, y.size)))
        rollout_guardrails = await rollout_guardrail_service.compare(
            candidate_mode="ml",
            baseline_mode="baseline",
            days=int(settings.MLOPS_GUARDRAIL_LOOKBACK_DAYS),
        )

        metrics = {
            "auc_default": float(round(auc_default_by_split["test"], 6)),
            "auc_learned": float(round(auc_learned_by_split["test"], 6)),
            "auc_gain": float(round(auc_gain_by_split["test"], 6)),
            "auc_default_train": float(round(auc_default_by_split["train"], 6)),
            "auc_default_validation": float(round(auc_default_by_split["validation"], 6)),
            "auc_default_test": float(round(auc_default_by_split["test"], 6)),
            "auc_learned_train": float(round(auc_learned_by_split["train"], 6)),
            "auc_learned_validation": float(round(auc_learned_by_split["validation"], 6)),
            "auc_learned_test": float(round(auc_learned_by_split["test"], 6)),
            "auc_gain_train": float(round(auc_gain_by_split["train"], 6)),
            "auc_gain_validation": float(round(auc_gain_by_split["validation"], 6)),
            "auc_gain_test": float(round(auc_gain_by_split["test"], 6)),
            "positive_rate": float(round(positive_rate, 6)),
            "rows": float(training_rows),
            "grid_step": float(grid_step),
        }
        training_metadata = self._build_training_metadata(
            splits=splits,
            window_start=window_start,
            window_end=window_end,
            label_window_hours=label_window_hours,
            grid_step=grid_step,
            baselines=baselines,
            rows=training_rows,
        )

        version = RankingModelVersion(
            name="ranking-weights-v2",
            is_active=False,
            weights=learned,
            metrics=metrics,
            baselines=baselines,
            trained_window_start=window_start,
            trained_window_end=window_end,
            training_rows=training_rows,
            label_window_hours=int(label_window_hours),
            split_strategy=splits.strategy,
            training_metadata=training_metadata,
            notes=notes,
        )
        await version.insert()

        decision = evaluate_activation_policy(
            auto_activate=bool(auto_activate),
            policy=activation_policy,
            auc_gain=auc_gain_by_split["test"],
            min_auc_gain=float(min_auc_gain_for_activation),
            positive_rate=positive_rate,
            min_positive_rate=float(min_positive_rate_for_activation),
            learned_weights=learned,
            baseline_weights=baseline_weights,
            max_weight_shift=float(max_weight_shift_for_activation),
            guardrail_report=rollout_guardrails,
            require_online_kpis=bool(settings.MLOPS_GUARDRAIL_REQUIRE_ONLINE_KPIS),
            max_apply_rate_drop=float(settings.MLOPS_GUARDRAIL_MAX_APPLY_RATE_DROP),
            max_freshness_regression_seconds=float(settings.MLOPS_GUARDRAIL_MAX_FRESHNESS_REGRESSION_SECONDS),
            max_latency_p95_regression_ms=float(settings.MLOPS_GUARDRAIL_MAX_LATENCY_P95_REGRESSION_MS),
            max_failure_rate_regression=float(settings.MLOPS_GUARDRAIL_MAX_FAILURE_RATE_REGRESSION),
            parity_enabled=bool(settings.MLOPS_PARITY_ENABLED),
            min_real_impressions_per_mode=int(settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE),
            min_real_requests_per_mode=int(settings.MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE),
            max_ctr_regression=float(settings.MLOPS_PARITY_MAX_CTR_REGRESSION),
            max_apply_rate_regression=float(settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION),
            min_offline_auc_gain_for_online_gates=float(settings.MLOPS_PARITY_MIN_OFFLINE_AUC_GAIN_FOR_ONLINE_GATES),
        )
        should_activate = bool(decision.should_activate)
        activation_reason = decision.reason
        if should_activate:
            await ranking_model_service.activate(model_id=str(version.id))

        metrics["auto_activated"] = 1.0 if should_activate else 0.0
        drift_snapshot = await self._latest_drift_snapshot()
        lifecycle = {
            "evaluated_at": datetime.utcnow().isoformat(),
            "activation_policy": decision.policy,
            "activation_reason": activation_reason,
            "activated": bool(should_activate),
            "diagnostics": decision.diagnostics,
        }
        model_card = self._build_model_card(
            metrics=metrics,
            baselines=baselines,
            lifecycle=lifecycle,
            training_metadata=training_metadata,
            drift_snapshot=drift_snapshot,
            weights=learned,
        )
        version.lifecycle = lifecycle
        version.model_card = model_card
        await version.save()

        return TrainingResult(
            weights=learned,
            metrics=metrics,
            baselines=baselines,
            lifecycle=lifecycle,
            training_rows=training_rows,
            window_start=window_start,
            window_end=window_end,
            auto_activated=bool(should_activate),
            activation_reason=activation_reason,
            split_strategy=splits.strategy,
            training_metadata=training_metadata,
            model_card=model_card,
        )


retraining_service = RetrainingService()
