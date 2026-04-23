from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin_user
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.user import User
from app.services.analytics_warehouse_service import analytics_warehouse_service

router = APIRouter()


@router.post("/warehouse/rebuild", response_model=dict)
async def rebuild_warehouse(
    lookback_days: int = 30,
    traffic_type: Literal["real", "simulated"] = "real",
    _: User = Depends(get_current_admin_user),
) -> Any:
    return await analytics_warehouse_service.rebuild(
        lookback_days=lookback_days,
        traffic_type=traffic_type,
    )


@router.get("/warehouse/daily", response_model=list[dict])
async def read_daily_aggregates(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    metric_type: Optional[str] = None,
    traffic_type: Literal["real", "simulated"] = "real",
    limit: int = 200,
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters = [AnalyticsDailyAggregate.traffic_type == traffic_type]
    if date_from:
        query_filters.append(AnalyticsDailyAggregate.date >= date_from)
    if date_to:
        query_filters.append(AnalyticsDailyAggregate.date <= date_to)
    if metric_type:
        query_filters.append(AnalyticsDailyAggregate.metric_type == metric_type)

    rows = await AnalyticsDailyAggregate.find_many(*query_filters).sort("-date").limit(max(1, min(limit, 2000))).to_list()
    return [row.model_dump() for row in rows]


@router.get("/warehouse/funnels", response_model=list[dict])
async def read_funnels(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    traffic_type: Literal["real", "simulated"] = "real",
    limit: int = 200,
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters = [AnalyticsFunnelAggregate.traffic_type == traffic_type]
    if date_from:
        query_filters.append(AnalyticsFunnelAggregate.date >= date_from)
    if date_to:
        query_filters.append(AnalyticsFunnelAggregate.date <= date_to)
    rows = await AnalyticsFunnelAggregate.find_many(*query_filters).sort("-date").limit(max(1, min(limit, 2000))).to_list()
    return [row.model_dump() for row in rows]


@router.get("/warehouse/cohorts", response_model=list[dict])
async def read_cohorts(
    traffic_type: Literal["real", "simulated"] = "real",
    cohort_date: Optional[str] = None,
    max_days_since_cohort: int = 30,
    limit: int = 500,
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters = [
        AnalyticsCohortAggregate.traffic_type == traffic_type,
        AnalyticsCohortAggregate.days_since_cohort <= max(0, min(max_days_since_cohort, 120)),
    ]
    if cohort_date:
        query_filters.append(AnalyticsCohortAggregate.cohort_date == cohort_date)
    rows = await AnalyticsCohortAggregate.find_many(*query_filters).sort("-cohort_date").limit(max(1, min(limit, 5000))).to_list()
    return [row.model_dump() for row in rows]


@router.get("/feature-store/rows", response_model=list[dict])
async def read_feature_rows(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    traffic_type: Literal["real", "simulated"] = "real",
    limit: int = 500,
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters = [FeatureStoreRow.traffic_type == traffic_type]
    if date_from:
        query_filters.append(FeatureStoreRow.date >= date_from)
    if date_to:
        query_filters.append(FeatureStoreRow.date <= date_to)
    rows = await FeatureStoreRow.find_many(*query_filters).sort("-date").limit(max(1, min(limit, 5000))).to_list()
    return [row.model_dump() for row in rows]
