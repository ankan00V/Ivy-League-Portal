from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


RAGFeedbackType = Literal["up", "down"]


class RAGFeedbackEvent(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    request_id: str = Field(json_schema_extra={"index": True}, min_length=1)
    query: str = Field(min_length=1)
    feedback: RAGFeedbackType = Field(json_schema_extra={"index": True})
    rag_template_label: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    rag_template_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    response_summary: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    surface: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "rag_feedback_events"
        indexes = [
            "user_id",
            "request_id",
            "feedback",
            "rag_template_label",
            "rag_template_version_id",
            "surface",
            "created_at",
        ]
