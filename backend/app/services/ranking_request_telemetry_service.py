from __future__ import annotations

from typing import Optional

from beanie import PydanticObjectId

from app.core.metrics import RANKING_REQUESTS_TOTAL, RANKING_REQUEST_LATENCY_MS
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.traffic import TrafficType


class RankingRequestTelemetryService:
    async def log(
        self,
        *,
        request_kind: str,
        surface: str,
        latency_ms: float,
        success: bool,
        user_id: Optional[PydanticObjectId] = None,
        ranking_mode: Optional[str] = None,
        experiment_key: Optional[str] = None,
        experiment_variant: Optional[str] = None,
        rag_template_label: Optional[str] = None,
        rag_template_version_id: Optional[str] = None,
        model_version_id: Optional[str] = None,
        results_count: int = 0,
        freshness_seconds: float | None = None,
        error_code: str | None = None,
        traffic_type: TrafficType = "real",
    ) -> RankingRequestTelemetry:
        normalized_mode = (ranking_mode or "unknown").strip().lower() or "unknown"
        normalized_key = (experiment_key or "none").strip().lower() or "none"
        normalized_variant = (experiment_variant or "none").strip().lower() or "none"
        normalized_traffic = (traffic_type or "real").strip().lower() or "real"
        normalized_kind = (request_kind or "unknown").strip().lower() or "unknown"
        normalized_success = "true" if bool(success) else "false"
        safe_latency_ms = max(0.0, float(latency_ms))
        if RANKING_REQUESTS_TOTAL is not None:
            RANKING_REQUESTS_TOTAL.labels(
                request_kind=normalized_kind,
                ranking_mode=normalized_mode,
                experiment_key=normalized_key,
                experiment_variant=normalized_variant,
                success=normalized_success,
                traffic_type=normalized_traffic,
            ).inc()
        if RANKING_REQUEST_LATENCY_MS is not None:
            RANKING_REQUEST_LATENCY_MS.labels(
                request_kind=normalized_kind,
                ranking_mode=normalized_mode,
                experiment_key=normalized_key,
                experiment_variant=normalized_variant,
                traffic_type=normalized_traffic,
            ).observe(safe_latency_ms)

        event = RankingRequestTelemetry(
            user_id=user_id,
            request_kind=request_kind,  # type: ignore[arg-type]
            surface=surface,
            latency_ms=safe_latency_ms,
            success=bool(success),
            ranking_mode=(ranking_mode or None),
            experiment_key=(experiment_key or None),
            experiment_variant=(experiment_variant or None),
            rag_template_label=(rag_template_label or None),
            rag_template_version_id=(rag_template_version_id or None),
            model_version_id=(model_version_id or None),
            results_count=max(0, int(results_count)),
            freshness_seconds=None if freshness_seconds is None else max(0.0, float(freshness_seconds)),
            error_code=(error_code or None),
            traffic_type=traffic_type,
        )
        await event.insert()
        return event


ranking_request_telemetry_service = RankingRequestTelemetryService()
