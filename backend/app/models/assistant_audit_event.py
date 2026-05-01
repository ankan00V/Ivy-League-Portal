from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.time import utc_now


class AssistantAuditEvent(Document):
    user_id: Optional[PydanticObjectId] = None
    surface: str = Field(default="global_chat")
    request_id: str = Field(min_length=1)
    route: str = Field(min_length=1)
    tool_name: Optional[str] = None
    prompt_version: str = Field(default="assistant.v2")
    latency_ms: float = Field(default=0.0, ge=0.0)
    success: bool = Field(default=True)
    citation_count: int = Field(default=0, ge=0)
    summary_used: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "assistant_audit_events"
        indexes = [
            "user_id",
            "surface",
            "request_id",
            "route",
            "tool_name",
            "prompt_version",
            "success",
            "created_at",
        ]
