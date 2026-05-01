from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.warehouse_export_run import WarehouseExportRun
from app.services.analytics_warehouse_service import analytics_warehouse_service


def _client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
    )
    if tls_needed:
        kwargs.update(
            {
                "tls": True,
                "tlsCAFile": certifi.where(),
                "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
            }
        )
    return kwargs


async def _run(*, lookback_days: int, traffic_type: str) -> dict[str, Any]:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            OpportunityInteraction,
            RankingRequestTelemetry,
            AnalyticsDailyAggregate,
            AnalyticsFunnelAggregate,
            AnalyticsCohortAggregate,
            FeatureStoreRow,
            WarehouseExportRun,
        ],
    )
    try:
        return await analytics_warehouse_service.rebuild(
            lookback_days=lookback_days,
            traffic_type=traffic_type,
        )
    finally:
        client.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rebuild analytics warehouse and feature-store tables.")
    parser.add_argument("--lookback-days", type=int, default=settings.ANALYTICS_LOOKBACK_DAYS_DEFAULT)
    parser.add_argument("--traffic-type", choices=["real", "simulated"], default="real")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    summary = asyncio.run(
        _run(
            lookback_days=max(1, int(args.lookback_days)),
            traffic_type=str(args.traffic_type).strip().lower(),
        )
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
