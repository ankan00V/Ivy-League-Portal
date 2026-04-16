from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

import numpy as np

from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion


def _bucket_query(query: Optional[str], buckets: int) -> int:
    value = (query or "").strip().lower()
    digest = md5(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(1, int(buckets))


def _psi(p: np.ndarray, q: np.ndarray, eps: float = 1e-6) -> float:
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    if p.size == 0 or q.size == 0 or p.size != q.size:
        return 0.0
    p = np.clip(p, eps, 1.0)
    q = np.clip(q, eps, 1.0)
    return float(np.sum((p - q) * np.log(p / q)))


def _mean_std(values: np.ndarray) -> tuple[float, float]:
    if values.size == 0:
        return 0.0, 0.0
    return float(values.mean()), float(values.std(ddof=0))


class DriftService:
    async def run(
        self,
        *,
        lookback_days: int = settings.MLOPS_DRIFT_LOOKBACK_DAYS,
        feature_keys: tuple[str, ...] = ("semantic_score", "baseline_score", "behavior_score"),
        psi_alert_threshold: float = settings.MLOPS_DRIFT_PSI_ALERT_THRESHOLD,
        z_alert_threshold: float = settings.MLOPS_DRIFT_Z_ALERT_THRESHOLD,
    ) -> ModelDriftReport:
        now = datetime.utcnow()
        window_start = now - timedelta(days=max(1, int(lookback_days)))
        window_end = now

        active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
        baselines = (active.baselines or {}) if active else {}

        impressions = await OpportunityInteraction.find_many(
            OpportunityInteraction.interaction_type == "impression",
            OpportunityInteraction.created_at >= window_start,
            OpportunityInteraction.created_at <= window_end,
        ).to_list()
        impressions = [item for item in impressions if isinstance(item.features, dict)]

        # Query bucket PSI (baseline vs recent).
        qb = baselines.get("query_buckets") or {}
        buckets = int(qb.get("buckets") or 128)
        baseline_dist = np.asarray(qb.get("dist") or [], dtype=np.float64)

        recent_counts = np.zeros((max(1, buckets),), dtype=np.int64)
        for imp in impressions:
            recent_counts[_bucket_query(imp.query, buckets)] += 1
        recent_total = int(recent_counts.sum())
        recent_dist = (recent_counts / float(recent_total)).astype(np.float64) if recent_total > 0 else recent_counts

        query_bucket_psi = _psi(baseline_dist, recent_dist) if baseline_dist.size == recent_dist.size else 0.0

        # Feature mean drift via z-score of mean shift.
        baseline_feature_stats = (baselines.get("features") or {}) if isinstance(baselines.get("features"), dict) else {}
        z_scores: dict[str, float] = {}
        recent_means: dict[str, float] = {}

        for key in feature_keys:
            values = np.asarray(
                [float((imp.features or {}).get(key) or 0.0) / 100.0 for imp in impressions],
                dtype=np.float64,
            )
            recent_mean, recent_std = _mean_std(values)
            recent_means[key] = float(round(recent_mean, 6))

            bstats = baseline_feature_stats.get(key) or {}
            baseline_mean = float(bstats.get("mean") or 0.0)
            baseline_std = float(bstats.get("std") or 0.0)
            denom = max(1e-6, baseline_std)
            z = abs(recent_mean - baseline_mean) / denom
            z_scores[key] = float(round(z, 6))

        metrics: dict[str, Any] = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "impressions": int(len(impressions)),
            "query_bucket_psi": float(round(query_bucket_psi, 6)),
            "psi_alert_threshold": float(round(psi_alert_threshold, 6)),
            "z_alert_threshold": float(round(z_alert_threshold, 6)),
            "recent_feature_means": recent_means,
            "feature_mean_z": z_scores,
            "max_feature_mean_z": float(round(max(z_scores.values()) if z_scores else 0.0, 6)),
            "baseline_available": bool(active and bool(baselines)),
        }

        alert = False
        if metrics["baseline_available"]:
            alert = (query_bucket_psi >= float(psi_alert_threshold)) or any(
                z >= float(z_alert_threshold) for z in z_scores.values()
            )

        report = ModelDriftReport(
            model_version_id=str(active.id) if active else None,
            window_start=window_start,
            window_end=window_end,
            metrics=metrics,
            alert=bool(alert),
        )
        await report.insert()
        return report


drift_service = DriftService()
