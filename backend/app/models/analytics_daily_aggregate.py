from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AnalyticsDailyAggregate(Document):
    date: str = Field(json_schema_extra={"index": True}, min_length=10, max_length=10)  # YYYY-MM-DD
    metric_type: str = Field(json_schema_extra={"index": True}, min_length=1)  # interaction | request
    traffic_type: str = Field(default="real", json_schema_extra={"index": True})
    ranking_mode: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_variant: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    request_kind: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "analytics_daily_aggregates"
        indexes = [
            IndexModel(
                [
                    ("date", 1),
                    ("metric_type", 1),
                    ("traffic_type", 1),
                    ("ranking_mode", 1),
                    ("experiment_key", 1),
                    ("experiment_variant", 1),
                    ("request_kind", 1),
                ], unique=True,
            ),
            "date",
            "metric_type",
            "traffic_type",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "request_kind",
            "updated_at",
        ]
