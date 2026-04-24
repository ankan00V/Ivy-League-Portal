from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class MlopsIncident(Document):
    incident_key: str = Field(min_length=1)
    source_type: str = Field(default="drift_alert", index=True)
    source_id: str = Field(min_length=1, index=True)
    report_id: Optional[str] = Field(default=None, index=True)
    model_version_id: Optional[str] = Field(default=None, index=True)
    severity: str = Field(default="error", index=True)
    status: str = Field(default="open", index=True)  # open | acknowledged | resolved
    title: str
    summary: str = ""
    owner: Optional[str] = Field(default=None, index=True)
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    lessons_learned: Optional[str] = None
    review_due_at: Optional[datetime] = None
    breached_sla: bool = Field(default=False, index=True)
    resolved_at: Optional[datetime] = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "mlops_incidents"
        indexes = [
            IndexModel([("incident_key", 1)], unique=True),
            "source_type",
            "source_id",
            "report_id",
            "model_version_id",
            "severity",
            "status",
            "owner",
            "breached_sla",
            "created_at",
            "updated_at",
        ]
