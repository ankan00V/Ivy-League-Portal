from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import quantiles
from typing import Any, Optional

from app.core.config import settings
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry


def _day_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    try:
        return float(quantiles(values, n=100, method="inclusive")[94])
    except Exception:
        ordered = sorted(values)
        idx = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
        return float(ordered[idx])


@dataclass(frozen=True)
class WarehouseBuildSummary:
    daily_rows: int
    funnel_rows: int
    cohort_rows: int
    feature_rows: int
    interactions_processed: int
    telemetry_processed: int


class AnalyticsWarehouseService:
    async def rebuild(
        self,
        *,
        lookback_days: int | None = None,
        traffic_type: str = "real",
    ) -> dict[str, Any]:
        if not settings.ANALYTICS_WAREHOUSE_ENABLED:
            return {"status": "disabled"}

        safe_days = max(1, min(int(lookback_days or settings.ANALYTICS_LOOKBACK_DAYS_DEFAULT), 365))
        since = datetime.utcnow() - timedelta(days=safe_days)
        normalized_traffic = (traffic_type or "real").strip().lower() or "real"

        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.created_at >= since,
            OpportunityInteraction.traffic_type == normalized_traffic,
        ).to_list()
        telemetry = await RankingRequestTelemetry.find_many(
            RankingRequestTelemetry.created_at >= since,
            RankingRequestTelemetry.traffic_type == normalized_traffic,
        ).to_list()

        await AnalyticsDailyAggregate.find_many(
            AnalyticsDailyAggregate.date >= _day_key(since),
            AnalyticsDailyAggregate.traffic_type == normalized_traffic,
        ).delete()
        await AnalyticsFunnelAggregate.find_many(
            AnalyticsFunnelAggregate.date >= _day_key(since),
            AnalyticsFunnelAggregate.traffic_type == normalized_traffic,
        ).delete()
        await AnalyticsCohortAggregate.find_many(
            AnalyticsCohortAggregate.traffic_type == normalized_traffic,
        ).delete()
        await FeatureStoreRow.find_many(
            FeatureStoreRow.date >= _day_key(since),
            FeatureStoreRow.traffic_type == normalized_traffic,
        ).delete()

        daily_rows = await self._build_daily_aggregates(interactions=interactions, telemetry=telemetry, traffic_type=normalized_traffic)
        funnel_rows = await self._build_funnel_aggregates(interactions=interactions, traffic_type=normalized_traffic)
        cohort_rows = await self._build_cohort_aggregates(interactions=interactions, traffic_type=normalized_traffic)
        feature_rows = await self._build_feature_store_rows(interactions=interactions, traffic_type=normalized_traffic)

        summary = WarehouseBuildSummary(
            daily_rows=daily_rows,
            funnel_rows=funnel_rows,
            cohort_rows=cohort_rows,
            feature_rows=feature_rows,
            interactions_processed=len(interactions),
            telemetry_processed=len(telemetry),
        )
        return {
            "status": "ok",
            "lookback_days": safe_days,
            "traffic_type": normalized_traffic,
            "daily_rows": summary.daily_rows,
            "funnel_rows": summary.funnel_rows,
            "cohort_rows": summary.cohort_rows,
            "feature_rows": summary.feature_rows,
            "interactions_processed": summary.interactions_processed,
            "telemetry_processed": summary.telemetry_processed,
        }

    async def _build_daily_aggregates(
        self,
        *,
        interactions: list[OpportunityInteraction],
        telemetry: list[RankingRequestTelemetry],
        traffic_type: str,
    ) -> int:
        grouped_interactions: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "impression": 0,
                "view": 0,
                "click": 0,
                "apply": 0,
                "save": 0,
                "unique_users": set(),
            }
        )
        for event in interactions:
            day = _day_key(event.created_at)
            key = (
                day,
                (event.ranking_mode or "unknown").strip().lower(),
                (event.experiment_key or "none").strip().lower(),
                (event.experiment_variant or "none").strip().lower(),
            )
            payload = grouped_interactions[key]
            action = (event.interaction_type or "view").strip().lower()
            if action not in {"impression", "view", "click", "apply", "save"}:
                action = "view"
            payload[action] += 1
            payload["unique_users"].add(str(event.user_id))

        grouped_requests: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "latencies": [],
            }
        )
        for event in telemetry:
            day = _day_key(event.created_at)
            key = (
                day,
                (event.request_kind or "unknown").strip().lower(),
                (event.ranking_mode or "unknown").strip().lower(),
                (event.experiment_key or "none").strip().lower(),
                (event.experiment_variant or "none").strip().lower(),
            )
            payload = grouped_requests[key]
            payload["requests"] += 1
            if bool(event.success):
                payload["successes"] += 1
            else:
                payload["failures"] += 1
            payload["latencies"].append(float(max(0.0, event.latency_ms)))

        docs: list[AnalyticsDailyAggregate] = []
        now = datetime.utcnow()
        for key, payload in grouped_interactions.items():
            day, mode, exp_key, exp_variant = key
            impressions = int(payload["impression"])
            clicks = int(payload["click"])
            applies = int(payload["apply"])
            saves = int(payload["save"])
            views = int(payload["view"])
            docs.append(
                AnalyticsDailyAggregate(
                    date=day,
                    metric_type="interaction",
                    traffic_type=traffic_type,
                    ranking_mode=mode,
                    experiment_key=exp_key,
                    experiment_variant=exp_variant,
                    request_kind=None,
                    metrics={
                        "impressions": impressions,
                        "views": views,
                        "clicks": clicks,
                        "applies": applies,
                        "saves": saves,
                        "unique_users": len(payload["unique_users"]),
                        "ctr": round(_safe_ratio(clicks, impressions), 8),
                        "apply_rate": round(_safe_ratio(applies, impressions), 8),
                        "save_rate": round(_safe_ratio(saves, impressions), 8),
                    },
                    created_at=now,
                    updated_at=now,
                )
            )

        for key, payload in grouped_requests.items():
            day, request_kind, mode, exp_key, exp_variant = key
            requests = int(payload["requests"])
            successes = int(payload["successes"])
            failures = int(payload["failures"])
            latencies = [float(value) for value in payload["latencies"]]
            docs.append(
                AnalyticsDailyAggregate(
                    date=day,
                    metric_type="request",
                    traffic_type=traffic_type,
                    ranking_mode=mode,
                    experiment_key=exp_key,
                    experiment_variant=exp_variant,
                    request_kind=request_kind,
                    metrics={
                        "requests": requests,
                        "successes": successes,
                        "failures": failures,
                        "failure_rate": round(_safe_ratio(failures, requests), 8),
                        "latency_mean_ms": round(_safe_ratio(sum(latencies), max(1, len(latencies))), 8),
                        "latency_p95_ms": round(_p95(latencies), 8),
                    },
                    created_at=now,
                    updated_at=now,
                )
            )

        if docs:
            await AnalyticsDailyAggregate.insert_many(docs)
        return len(docs)

    async def _build_funnel_aggregates(
        self,
        *,
        interactions: list[OpportunityInteraction],
        traffic_type: str,
    ) -> int:
        grouped: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(
            lambda: {"impression": 0, "view": 0, "click": 0, "save": 0, "apply": 0}
        )
        for event in interactions:
            key = (
                _day_key(event.created_at),
                (event.ranking_mode or "unknown").strip().lower(),
                (event.experiment_key or "none").strip().lower(),
                (event.experiment_variant or "none").strip().lower(),
            )
            action = (event.interaction_type or "view").strip().lower()
            if action in grouped[key]:
                grouped[key][action] += 1

        docs: list[AnalyticsFunnelAggregate] = []
        now = datetime.utcnow()
        for key, counts in grouped.items():
            day, mode, exp_key, exp_variant = key
            impressions = int(counts["impression"])
            views = int(counts["view"])
            clicks = int(counts["click"])
            saves = int(counts["save"])
            applies = int(counts["apply"])
            docs.append(
                AnalyticsFunnelAggregate(
                    date=day,
                    traffic_type=traffic_type,
                    ranking_mode=mode,
                    experiment_key=exp_key,
                    experiment_variant=exp_variant,
                    stage_counts={
                        "impression": impressions,
                        "view": views,
                        "click": clicks,
                        "save": saves,
                        "apply": applies,
                    },
                    rates={
                        "view_from_impression": round(_safe_ratio(views, impressions), 8),
                        "click_from_impression": round(_safe_ratio(clicks, impressions), 8),
                        "save_from_click": round(_safe_ratio(saves, clicks), 8),
                        "apply_from_click": round(_safe_ratio(applies, clicks), 8),
                    },
                    metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
        if docs:
            await AnalyticsFunnelAggregate.insert_many(docs)
        return len(docs)

    async def _build_cohort_aggregates(
        self,
        *,
        interactions: list[OpportunityInteraction],
        traffic_type: str,
    ) -> int:
        if not interactions:
            return 0

        by_user: dict[str, list[OpportunityInteraction]] = defaultdict(list)
        for event in interactions:
            by_user[str(event.user_id)].append(event)
        for rows in by_user.values():
            rows.sort(key=lambda row: row.created_at)

        cohort_users: dict[str, set[str]] = defaultdict(set)
        activity_by_cohort_day: dict[tuple[str, int], set[str]] = defaultdict(set)
        apply_by_cohort_day: dict[tuple[str, int], set[str]] = defaultdict(set)

        for user_id, rows in by_user.items():
            first_day = _day_key(rows[0].created_at)
            cohort_users[first_day].add(user_id)
            first_date = rows[0].created_at.date()
            for row in rows:
                delta = (row.created_at.date() - first_date).days
                if delta < 0 or delta > 60:
                    continue
                key = (first_day, int(delta))
                activity_by_cohort_day[key].add(user_id)
                if (row.interaction_type or "").strip().lower() == "apply":
                    apply_by_cohort_day[key].add(user_id)

        docs: list[AnalyticsCohortAggregate] = []
        now = datetime.utcnow()
        for cohort_date, users in cohort_users.items():
            cohort_size = len(users)
            for delta in range(0, 61):
                key = (cohort_date, delta)
                active_users = len(activity_by_cohort_day.get(key, set()))
                applying_users = len(apply_by_cohort_day.get(key, set()))
                docs.append(
                    AnalyticsCohortAggregate(
                        cohort_date=cohort_date,
                        days_since_cohort=delta,
                        traffic_type=traffic_type,
                        users_in_cohort=cohort_size,
                        active_users=active_users,
                        applying_users=applying_users,
                        retention_rate=round(_safe_ratio(active_users, cohort_size), 8),
                        apply_rate=round(_safe_ratio(applying_users, cohort_size), 8),
                        created_at=now,
                        updated_at=now,
                    )
                )

        if docs:
            await AnalyticsCohortAggregate.insert_many(docs)
        return len(docs)

    async def _build_feature_store_rows(
        self,
        *,
        interactions: list[OpportunityInteraction],
        traffic_type: str,
    ) -> int:
        if not interactions:
            return 0

        label_window = timedelta(hours=max(1, int(settings.FEATURE_STORE_LABEL_WINDOW_HOURS)))
        by_user_opp: dict[tuple[str, str], list[OpportunityInteraction]] = defaultdict(list)
        for event in interactions:
            key = (str(event.user_id), str(event.opportunity_id))
            by_user_opp[key].append(event)
        for rows in by_user_opp.values():
            rows.sort(key=lambda row: row.created_at)

        docs: list[FeatureStoreRow] = []
        now = datetime.utcnow()
        for (user_id, opportunity_id), rows in by_user_opp.items():
            for idx, event in enumerate(rows):
                if (event.interaction_type or "").strip().lower() != "impression":
                    continue
                labels = {"clicked": 0, "saved": 0, "applied": 0}
                cutoff = event.created_at + label_window
                for later in rows[idx + 1 :]:
                    if later.created_at > cutoff:
                        break
                    action = (later.interaction_type or "").strip().lower()
                    if action == "click":
                        labels["clicked"] = 1
                    elif action == "save":
                        labels["saved"] = 1
                    elif action == "apply":
                        labels["applied"] = 1

                docs.append(
                    FeatureStoreRow(
                        row_key=f"{str(event.id)}",
                        date=_day_key(event.created_at),
                        user_id=user_id,
                        opportunity_id=opportunity_id,
                        ranking_mode=(event.ranking_mode or "unknown"),
                        experiment_key=(event.experiment_key or "none"),
                        experiment_variant=(event.experiment_variant or "none"),
                        traffic_type=traffic_type,
                        rank_position=event.rank_position,
                        match_score=event.match_score,
                        features=dict(event.features or {}),
                        labels=labels,
                        source_event_id=str(event.id),
                        created_at=now,
                        updated_at=now,
                    )
                )

        if docs:
            await FeatureStoreRow.insert_many(docs)
        return len(docs)


analytics_warehouse_service = AnalyticsWarehouseService()
