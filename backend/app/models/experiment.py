from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Literal, Optional
from uuid import uuid4

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel


RankingMode = Literal["baseline", "semantic", "ml", "ab"]
PrimaryMetric = Literal["ctr", "apply_rate", "save_rate", "session_depth"]


class ExperimentVariant(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0.0)
    traffic_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ranking_mode: Optional[RankingMode] = None
    description: Optional[str] = None
    exclude_cold_start: bool = False
    is_control: bool = False


ExperimentStatus = Literal["draft", "running", "paused", "concluded", "active", "archived"]


class Experiment(Document):
    key: Indexed(str, unique=True)  # type: ignore[valid-type]
    name: Optional[str] = None
    description: Optional[str] = None
    status: ExperimentStatus = "active"
    variants: list[ExperimentVariant] = Field(default_factory=list)
    start_date: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    end_date: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    min_sample_size: int = Field(default=200, ge=1)
    primary_metric: PrimaryMetric = "ctr"
    guardrail_metrics: list[str] = Field(default_factory=lambda: ["apply_rate", "save_rate"])
    default_variant: Optional[str] = None
    winning_variant: Optional[str] = None
    graduated_at: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    graduation_history: list[dict[str, Any]] = Field(default_factory=list)
    # Salt can be rotated to re-randomize future assignments; existing users remain sticky via assignments collection.
    salt: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "experiments"
        indexes = [
            "key",
            "status",
            "start_date",
            "end_date",
            "graduated_at",
            "updated_at",
        ]


class ExperimentAssignment(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    experiment_key: str = Field(json_schema_extra={"index": True})
    variant: str
    bucket: int = Field(ge=0, le=9999)
    bucket_percent: int = Field(default=0, ge=0, le=99)
    assigned_via_exclusion: bool = False
    exclusion_reason: Optional[str] = None
    assigned_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "experiment_assignments"
        indexes = [
            IndexModel([("user_id", 1), ("experiment_key", 1)], unique=True),
            "experiment_key",
            "variant",
            "assigned_at",
        ]
