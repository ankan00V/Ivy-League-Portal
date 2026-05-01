from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from beanie.odm.operators.find.comparison import In

from app.core.time import utc_now
from app.core.metrics import (
    ASSISTANT_QUALITY_VALUE,
    FEATURE_FRESHNESS_SECONDS,
    MODEL_INPUT_DRIFT_VALUE,
    MODEL_PROMOTION_INFO,
    PARITY_SCORECARD_VALUE,
    RANKING_SLICE_RATE,
)
from app.models.assistant_audit_event import AssistantAuditEvent
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


def _slice_label(value: Any) -> str:
    if isinstance(value, list):
        value = ",".join(str(item) for item in value[:3])
    text = str(value or "unknown").strip().lower()
    return text or "unknown"


class DataScienceObservabilityService:
    async def feature_freshness_summary(self) -> dict[str, Any]:
        latest = await FeatureStoreRow.find_many().sort("-updated_at").limit(1).to_list()
        count = await FeatureStoreRow.find_many().count()
        latest_row = latest[0] if latest else None
        now = utc_now()
        freshness_seconds = None
        if latest_row and latest_row.updated_at:
            freshness_seconds = max(0.0, (now - latest_row.updated_at).total_seconds())
        if FEATURE_FRESHNESS_SECONDS is not None:
            FEATURE_FRESHNESS_SECONDS.set(float(freshness_seconds or 0.0))
        return {
            "rows": int(count),
            "latest_feature_at": latest_row.updated_at if latest_row else None,
            "freshness_seconds": freshness_seconds,
        }

    async def drift_summary(self, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = await ModelDriftReport.find_many().sort("-created_at").limit(max(1, min(int(limit), 20))).to_list()
        payload = [
            {
                "id": str(row.id),
                "model_version_id": row.model_version_id,
                "alert": bool(row.alert),
                "created_at": row.created_at,
                "metrics": dict(row.metrics or {}),
            }
            for row in rows
        ]
        if payload and MODEL_INPUT_DRIFT_VALUE is not None:
            latest_metrics = dict(payload[0].get("metrics") or {})
            for metric in ("query_bucket_psi", "max_feature_mean_z", "impressions"):
                MODEL_INPUT_DRIFT_VALUE.labels(metric=metric).set(float(latest_metrics.get(metric) or 0.0))
            MODEL_INPUT_DRIFT_VALUE.labels(metric="alert").set(1.0 if payload[0].get("alert") else 0.0)
        return payload

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
        payload = {
            "lookback_days": int(lookback_days),
            "offline": {
                "auc_default": float(model_metrics.get("auc_default", 0.0) or 0.0),
                "auc_learned": float(model_metrics.get("auc_learned", 0.0) or 0.0),
                "auc_gain": float(model_metrics.get("auc_gain", 0.0) or 0.0),
            },
            "online": online,
        }
        if PARITY_SCORECARD_VALUE is not None:
            offline = dict(payload["offline"])
            for metric, value in offline.items():
                PARITY_SCORECARD_VALUE.labels(mode="offline", metric=str(metric)).set(float(value or 0.0))
            for mode, values in online.items():
                for metric, value in dict(values).items():
                    PARITY_SCORECARD_VALUE.labels(mode=str(mode), metric=str(metric)).set(float(value or 0.0))
        return payload

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
            domain = _slice_label(getattr(opp, "domain", None))
            institution = _slice_label(getattr(opp, "university", None) or getattr(profile, "college_name", None))
            geography = _slice_label(getattr(opp, "location", None) or getattr(profile, "preferred_locations", None))
            segment = _slice_label(getattr(profile, "user_type", None))
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

        payload = {
            "domain": summarize(domain_stats),
            "institution": summarize(institution_stats),
            "geography": summarize(geography_stats),
            "segment": summarize(segment_stats),
        }
        if RANKING_SLICE_RATE is not None:
            for slice_type, rows in payload.items():
                for row in rows:
                    slice_name = str(row.get("slice") or "unknown")[:120]
                    for metric in ("ctr", "apply_rate", "impressions"):
                        RANKING_SLICE_RATE.labels(
                            slice_type=str(slice_type),
                            slice_name=slice_name,
                            metric=metric,
                        ).set(float(row.get(metric) or 0.0))
        return payload

    async def assistant_quality_summary(self, *, lookback_days: int = 7) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, min(int(lookback_days), 90)))
        rows = await RankingRequestTelemetry.find_many(
            RankingRequestTelemetry.request_kind == "assistant_chat",
            RankingRequestTelemetry.created_at >= since,
        ).to_list()
        audits = await AssistantAuditEvent.find_many(AssistantAuditEvent.created_at >= since).to_list()
        total = len(rows)
        failures = len([row for row in rows if not bool(row.success)])
        latencies = [float(row.latency_ms or 0.0) for row in rows]
        latency_mean = sum(latencies) / float(max(1, len(latencies)))
        route_counts: dict[str, int] = defaultdict(int)
        prompt_counts: dict[str, int] = defaultdict(int)
        citation_total = 0
        hallucination_flags = 0
        citation_correctness_scores: list[float] = []
        for audit in audits:
            route = (audit.route or "unknown").strip().lower() or "unknown"
            prompt_version = (audit.prompt_version or "unknown").strip() or "unknown"
            route_counts[route] += 1
            prompt_counts[prompt_version] += 1
            citation_total += int(getattr(audit, "citation_count", 0) or (audit.metadata or {}).get("citations") or 0)
            if bool((audit.metadata or {}).get("hallucination_flag")):
                hallucination_flags += 1
            if (audit.metadata or {}).get("citation_correctness") is not None:
                citation_correctness_scores.append(float((audit.metadata or {}).get("citation_correctness") or 0.0))
        citation_correctness = (
            sum(citation_correctness_scores) / float(len(citation_correctness_scores))
            if citation_correctness_scores
            else None
        )
        payload = {
            "requests": total,
            "failure_rate": round(_safe_ratio(failures, total), 6),
            "latency_mean_ms": round(latency_mean, 3),
            "audit_events": len(audits),
            "routes": dict(sorted(route_counts.items())),
            "prompt_versions": dict(sorted(prompt_counts.items())),
            "citation_count": citation_total,
            "hallucination_rate": round(_safe_ratio(hallucination_flags, len(audits)), 6),
            "citation_correctness": None if citation_correctness is None else round(citation_correctness, 6),
        }
        if ASSISTANT_QUALITY_VALUE is not None:
            prompt_label = ",".join(sorted(prompt_counts.keys()))[:120] or "unknown"
            ASSISTANT_QUALITY_VALUE.labels(metric="failure_rate", prompt_version=prompt_label, route="all").set(payload["failure_rate"])
            ASSISTANT_QUALITY_VALUE.labels(metric="latency_mean_ms", prompt_version=prompt_label, route="all").set(payload["latency_mean_ms"])
            ASSISTANT_QUALITY_VALUE.labels(metric="hallucination_rate", prompt_version=prompt_label, route="all").set(payload["hallucination_rate"])
            ASSISTANT_QUALITY_VALUE.labels(
                metric="citation_correctness",
                prompt_version=prompt_label,
                route="all",
            ).set(float(payload["citation_correctness"] or 0.0))
            for route, count in route_counts.items():
                ASSISTANT_QUALITY_VALUE.labels(metric="route_count", prompt_version=prompt_label, route=route).set(float(count))
        return payload

    async def model_promotion_history(self, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = await RankingModelVersion.find_many().sort("-created_at").limit(max(1, min(int(limit), 50))).to_list()
        payload = []
        for row in rows:
            lifecycle = dict(row.lifecycle or {})
            reason = str(lifecycle.get("activation_reason") or lifecycle.get("promotion_reason") or "n/a")
            status = "active" if bool(row.is_active) else "candidate"
            item = {
                "id": str(row.id),
                "name": row.name,
                "status": status,
                "created_at": row.created_at,
                "training_rows": int(row.training_rows or 0),
                "auc_gain": float((row.metrics or {}).get("auc_gain_test") or (row.metrics or {}).get("auc_gain") or 0.0),
                "activation_reason": reason,
                "artifact_uri": row.artifact_uri,
                "serving_ready": bool(row.serving_ready),
            }
            payload.append(item)
            if MODEL_PROMOTION_INFO is not None:
                MODEL_PROMOTION_INFO.labels(
                    model_id=item["id"][:32],
                    model_name=str(row.name or "unknown")[:80],
                    status=status,
                    reason=reason[:120],
                ).set(1.0 if row.is_active else 0.0)
        return payload

    async def operating_loop_snapshot(self, *, lookback_days: int = 30) -> dict[str, Any]:
        return {
            "generated_at": utc_now(),
            "lookback_days": int(lookback_days),
            "feature_freshness": await self.feature_freshness_summary(),
            "drift": await self.drift_summary(limit=10),
            "parity": await self.parity_scorecard(lookback_days=lookback_days),
            "slice_metrics": await self.ranking_slice_metrics(lookback_days=lookback_days, limit=20),
            "assistant_quality": await self.assistant_quality_summary(lookback_days=min(lookback_days, 90)),
            "model_promotions": await self.model_promotion_history(limit=20),
        }


data_science_observability_service = DataScienceObservabilityService()
