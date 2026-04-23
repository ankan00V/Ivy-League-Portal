from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.models.traffic import TrafficType

RequestKind = Literal["recommended", "shortlist", "ask_ai"]


class RankingRequestTelemetry(Document):
    user_id: Optional[PydanticObjectId] = Field(default=None, index=True)
    request_kind: RequestKind = Field(index=True)
    ranking_mode: Optional[str] = Field(default=None, index=True)
    experiment_key: Optional[str] = Field(default=None, index=True)
    experiment_variant: Optional[str] = Field(default=None, index=True)
    rag_template_label: Optional[str] = Field(default=None, index=True)
    rag_template_version_id: Optional[str] = Field(default=None, index=True)
    model_version_id: Optional[str] = Field(default=None, index=True)
    surface: Optional[str] = Field(default=None, index=True)
    success: bool = Field(default=True, index=True)
    latency_ms: float = Field(default=0.0, ge=0.0)
    results_count: int = Field(default=0, ge=0)
    freshness_seconds: Optional[float] = Field(default=None, ge=0.0)
    error_code: Optional[str] = None
    traffic_type: TrafficType = Field(default="real", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "ranking_request_telemetry"
        indexes = [
            "request_kind",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "rag_template_label",
            "rag_template_version_id",
            "model_version_id",
            "surface",
            "success",
            "traffic_type",
            "created_at",
        ]
