from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class RecruiterAuditLog(Document):
    recruiter_user_id: PydanticObjectId = Field(index=True)
    action: str = Field(index=True, min_length=1)
    entity_type: str = Field(index=True, min_length=1)
    entity_id: Optional[str] = Field(default=None, index=True)
    opportunity_id: Optional[PydanticObjectId] = Field(default=None, index=True)
    application_id: Optional[PydanticObjectId] = Field(default=None, index=True)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "recruiter_audit_logs"
        indexes = [
            "recruiter_user_id",
            "action",
            "entity_type",
            "entity_id",
            "opportunity_id",
            "application_id",
            "created_at",
        ]
