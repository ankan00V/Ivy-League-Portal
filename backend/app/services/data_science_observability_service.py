from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from beanie.odm.operators.find.comparison import In

from app.core.time import utc_now
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.feature_store_row import FeatureStoreRow


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


class DataScienceObservabilityService:
    async def feature_freshness_summary(self) -> dict[str, Any]:
        latest = await FeatureStoreRow.find_many().sort("-updated_at").limit(1).to_list()
        count = await FeatureStoreRow.find_many().count()
        latest_row = latest[0] if latest else None
        now = utc_now()
        freshness_seconds = None
        if latest_row and latest_row.updated_at:
            freshness_seconds = max(0.0, (now - latest_row.updated_at).total_seconds())
        return {
            "rows": int(count),
            "latest_feature_at": latest_row.updated_at if latest_row else None,
            "freshness_seconds": freshness_seconds,
        }

    async def drift_summary(self, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = await ModelDriftReport.find_many().sort("-created_at").limit(max(1, min(int(limit), 20))).to_list()
        return [
            {
                "id": str(row.id),
                "model_version_id": row.model_version_id,
                "alert": bool(row.alert),
                "created_at": row.created_at,
                "metrics": dict(row.metrics or {}),
            }
            for row in rows
        ]

    async def parity_scorecard(self, *, lookback_days: int = 30) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, min(int(lookback_days), 365)))
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.created_at >= since,
            OpportunityInteraction.traffic_type == "real",
        ).to_list()
        latest_model = await RankingModelVersion.find_many().sort("-created_at").limit(1).to_list()
        model_metrics = dict(latest_model[0].metrics or {}) if latest_model else {}

        buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"impression": 0.0, "click": 0.0, "apply": 0.0})
        for row in interactions:
            mode = (row.ranking_mode or "unknown").strip().lower() or "unknown"
            action = (row.interaction_type or "view").strip().lower()
            if action in buckets[mode]:
                buckets[mode][action] += 1.0

        online = {
            mode: {
                "impressions": int(values["impression"]),
                "ctr": round(_safe_ratio(values["click"], values["impression"]), 6),
                "apply_rate": round(_safe_ratio(values["apply"], values["impression"]), 6),
            }
            for mode, values in buckets.items()
        }
        return {
            "lookback_days": int(lookback_days),
            "offline": {
                "auc_default": float(model_metrics.get("auc_default", 0.0) or 0.0),
                "auc_learned": float(model_metrics.get("auc_learned", 0.0) or 0.0),
                "auc_gain": float(model_metrics.get("auc_gain", 0.0) or 0.0),
            },
            "online": online,
        }

    async def ranking_slice_metrics(self, *, lookback_days: int = 30, limit: int = 5) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, min(int(lookback_days), 365)))
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.created_at >= since,
            OpportunityInteraction.traffic_type == "real",
        ).to_list()
        opportunity_ids = list({row.opportunity_id for row in interactions if row.opportunity_id is not None})
        user_ids = list({row.user_id for row in interactions if row.user_id is not None})
        opportunities = await Opportunity.find_many(In(Opportunity.id, opportunity_ids)).to_list() if opportunity_ids else []
        profiles = await Profile.find_many(In(Profile.user_id, user_ids)).to_list() if user_ids else []
        opportunity_map = {str(row.id): row for row in opportunities}
        profile_map = {str(row.user_id): row for row in profiles}

        def new_bucket() -> dict[str, float]:
            return {"impressions": 0.0, "clicks": 0.0, "applies": 0.0}

        domain_stats: dict[str, dict[str, float]] = defaultdict(new_bucket)
        institution_stats: dict[str, dict[str, float]] = defaultdict(new_bucket)
        geography_stats: dict[str, dict[str, float]] = defaultdict(new_bucket)
        segment_stats: dict[str, dict[str, float]] = defaultdict(new_bucket)

        for row in interactions:
            action = (row.interaction_type or "").strip().lower()
            opp = opportunity_map.get(str(row.opportunity_id))
            profile = profile_map.get(str(row.user_id))
            domain = (getattr(opp, "domain", None) or "unknown").strip().lower()
            institution = (getattr(opp, "university", None) or getattr(profile, "college_name", None) or "unknown").strip().lower()
            geography = (getattr(opp, "location", None) or getattr(profile, "preferred_locations", None) or "unknown").strip().lower()
            segment = (getattr(profile, "user_type", None) or "unknown").strip().lower()
            for bucket in (domain_stats[domain], institution_stats[institution], geography_stats[geography], segment_stats[segment]):
                if action == "impression":
                    bucket["impressions"] += 1.0
                elif action == "click":
                    bucket["clicks"] += 1.0
                elif action == "apply":
                    bucket["applies"] += 1.0

        def summarize(source: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
            ranked = sorted(source.items(), key=lambda item: item[1]["impressions"], reverse=True)
            rows: list[dict[str, Any]] = []
            for name, values in ranked[: max(1, min(int(limit), 20))]:
                impressions = values["impressions"]
                rows.append(
                    {
                        "slice": name,
                        "impressions": int(impressions),
                        "clicks": int(values["clicks"]),
                        "applies": int(values["applies"]),
                        "ctr": round(_safe_ratio(values["clicks"], impressions), 6),
                        "apply_rate": round(_safe_ratio(values["applies"], impressions), 6),
                    }
                )
            return rows

        return {
            "domain": summarize(domain_stats),
            "institution": summarize(institution_stats),
            "geography": summarize(geography_stats),
            "segment": summarize(segment_stats),
        }

    async def assistant_quality_summary(self, *, lookback_days: int = 7) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, min(int(lookback_days), 90)))
        rows = await RankingRequestTelemetry.find_many(
            RankingRequestTelemetry.request_kind == "assistant_chat",
            RankingRequestTelemetry.created_at >= since,
        ).to_list()
        total = len(rows)
        failures = len([row for row in rows if not bool(row.success)])
        latencies = [float(row.latency_ms or 0.0) for row in rows]
        latency_mean = sum(latencies) / float(max(1, len(latencies)))
        return {
            "requests": total,
            "failure_rate": round(_safe_ratio(failures, total), 6),
            "latency_mean_ms": round(latency_mean, 3),
        }


data_science_observability_service = DataScienceObservabilityService()
