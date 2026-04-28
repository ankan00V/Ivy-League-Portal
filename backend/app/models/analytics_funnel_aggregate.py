from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AnalyticsFunnelAggregate(Document):
    date: str = Field(json_schema_extra={"index": True}, min_length=10, max_length=10)
    traffic_type: str = Field(default="real", json_schema_extra={"index": True})
    ranking_mode: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_variant: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    stage_counts: dict[str, int] = Field(default_factory=dict)
    rates: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "analytics_funnel_aggregates"
        indexes = [
            IndexModel(
                [
                    ("date", 1),
                    ("traffic_type", 1),
                    ("ranking_mode", 1),
                    ("experiment_key", 1),
                    ("experiment_variant", 1),
                ], unique=True,
            ),
            "date",
            "traffic_type",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "updated_at",
        ]
