from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class RankingModelVersion(Document):
    """
    Lightweight model registry for ranking-weight versions.

    Stores learned weights for combining:
      - semantic_score
      - baseline_score
      - behavior_score
    """

    name: str = "ranking-weights-v1"
    is_active: bool = False

    weights: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)

    trained_window_start: Optional[datetime] = None
    trained_window_end: Optional[datetime] = None
    training_rows: int = 0
    label_window_hours: int = 72
    split_strategy: str = "time"
    artifact_uri: Optional[str] = None
    artifact_provider: Optional[str] = None
    feature_schema: dict[str, Any] = Field(default_factory=dict)
    serving_ready: bool = False

    baselines: dict[str, Any] = Field(default_factory=dict)
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    training_metadata: dict[str, Any] = Field(default_factory=dict)
    model_card: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "ranking_model_versions"
        indexes = [
            "created_at",
            "is_active",
            "name",
        ]
