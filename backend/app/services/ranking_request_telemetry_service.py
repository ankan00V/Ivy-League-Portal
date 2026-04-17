from __future__ import annotations

from typing import Optional

from beanie import PydanticObjectId

from app.models.ranking_request_telemetry import RankingRequestTelemetry


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
        model_version_id: Optional[str] = None,
        results_count: int = 0,
        freshness_seconds: float | None = None,
        error_code: str | None = None,
    ) -> RankingRequestTelemetry:
        event = RankingRequestTelemetry(
            user_id=user_id,
            request_kind=request_kind,  # type: ignore[arg-type]
            surface=surface,
            latency_ms=max(0.0, float(latency_ms)),
            success=bool(success),
            ranking_mode=(ranking_mode or None),
            experiment_key=(experiment_key or None),
            experiment_variant=(experiment_variant or None),
            model_version_id=(model_version_id or None),
            results_count=max(0, int(results_count)),
            freshness_seconds=None if freshness_seconds is None else max(0.0, float(freshness_seconds)),
            error_code=(error_code or None),
        )
        await event.insert()
        return event


ranking_request_telemetry_service = RankingRequestTelemetryService()
