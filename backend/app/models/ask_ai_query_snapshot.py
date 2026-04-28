from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class AskAIQuerySnapshot(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    request_id: str = Field(json_schema_extra={"index": True}, min_length=1)
    surface: str = Field(default="opportunities_page", min_length=1, json_schema_extra={"index": True})
    query: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    response_summary: Optional[str] = None
    deadline_urgency: Optional[str] = None
    recommended_action: Optional[str] = None
    citation_count: int = Field(default=0, ge=0)
    top_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "ask_ai_query_snapshots"
        indexes = [
            IndexModel([("user_id", 1), ("request_id", 1)], unique=True),
            IndexModel([("user_id", 1), ("surface", 1), ("created_at", -1)]),
            "user_id",
            "request_id",
            "surface",
            "created_at",
        ]
