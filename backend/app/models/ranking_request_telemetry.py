from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.models.traffic import TrafficType
from app.core.time import utc_now

RequestKind = Literal["recommended", "shortlist", "ask_ai", "assistant_chat"]


class RankingRequestTelemetry(Document):
    user_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    request_kind: RequestKind = Field(json_schema_extra={"index": True})
    requested_ranking_mode: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    ranking_mode: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_variant: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    rollout_variant: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    rollout_bucket: Optional[int] = Field(default=None, ge=0, le=9999)
    rollout_percent: Optional[int] = Field(default=None, ge=0, le=100)
    shadow_mode: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    shadow_model_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    shadow_candidate_count: int = Field(default=0, ge=0)
    rag_template_label: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    rag_template_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    model_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    surface: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    success: bool = Field(default=True, json_schema_extra={"index": True})
    latency_ms: float = Field(default=0.0, ge=0.0)
    results_count: int = Field(default=0, ge=0)
    freshness_seconds: Optional[float] = Field(default=None, ge=0.0)
    error_code: Optional[str] = None
    traffic_type: TrafficType = Field(default="real", json_schema_extra={"index": True})
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "ranking_request_telemetry"
        indexes = [
            "request_kind",
            "requested_ranking_mode",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "rollout_variant",
            "shadow_mode",
            "shadow_model_version_id",
            "rag_template_label",
            "rag_template_version_id",
            "model_version_id",
            "surface",
            "success",
            "traffic_type",
            "created_at",
        ]
