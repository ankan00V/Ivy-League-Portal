from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class FeatureStoreRow(Document):
    row_key: str = Field(min_length=1)
    date: str = Field(index=True, min_length=10, max_length=10)
    user_id: Optional[str] = Field(default=None, index=True)
    opportunity_id: Optional[str] = Field(default=None, index=True)
    ranking_mode: Optional[str] = Field(default=None, index=True)
    experiment_key: Optional[str] = Field(default=None, index=True)
    experiment_variant: Optional[str] = Field(default=None, index=True)
    traffic_type: str = Field(default="real", index=True)
    rank_position: Optional[int] = None
    match_score: Optional[float] = None
    features: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    source_event_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "feature_store_rows"
        indexes = [
            IndexModel([("row_key", 1)], unique=True),
            "date",
            "user_id",
            "opportunity_id",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "traffic_type",
            "source_event_id",
            "updated_at",
        ]
