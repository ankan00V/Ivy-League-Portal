from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class ModelDriftReport(Document):
    model_version_id: Optional[str] = None
    window_start: datetime
    window_end: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)
    alert: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "model_drift_reports"
        indexes = [
            "created_at",
            "model_version_id",
            "alert",
        ]

