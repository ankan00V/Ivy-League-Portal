from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


RAGFeedbackType = Literal["up", "down"]


class RAGFeedbackEvent(Document):
    user_id: PydanticObjectId = Field(index=True)
    request_id: str = Field(index=True, min_length=1)
    query: str = Field(min_length=1)
    feedback: RAGFeedbackType = Field(index=True)
    response_summary: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    surface: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "rag_feedback_events"
        indexes = [
            "user_id",
            "request_id",
            "feedback",
            "surface",
            "created_at",
        ]
