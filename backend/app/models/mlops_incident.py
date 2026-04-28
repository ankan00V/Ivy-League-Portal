from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class MlopsIncident(Document):
    incident_key: str = Field(min_length=1)
    source_type: str = Field(default="drift_alert", json_schema_extra={"index": True})
    source_id: str = Field(min_length=1, json_schema_extra={"index": True})
    report_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    model_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    severity: str = Field(default="error", json_schema_extra={"index": True})
    status: str = Field(default="open", json_schema_extra={"index": True})  # open | acknowledged | resolved
    title: str
    summary: str = ""
    owner: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    lessons_learned: Optional[str] = None
    review_due_at: Optional[datetime] = None
    breached_sla: bool = Field(default=False, json_schema_extra={"index": True})
    resolved_at: Optional[datetime] = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

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
