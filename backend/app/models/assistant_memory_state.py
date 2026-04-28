from __future__ import annotations

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.time import utc_now


class AssistantMemoryState(Document):
    user_id: PydanticObjectId
    surface: str = Field(default="global_chat", min_length=1)
    summary: str = Field(default="", min_length=0)
    summarized_turns: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "assistant_memory_states"
        indexes = [
            "user_id",
            "surface",
            "updated_at",
        ]
