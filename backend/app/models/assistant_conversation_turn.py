from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class AssistantConversationTurn(Document):
    user_id: PydanticObjectId = Field(index=True)
    surface: str = Field(default="global_chat", min_length=1, index=True)
    role: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Settings:
        name = "assistant_conversation_turns"
        indexes = [
            IndexModel([("user_id", 1), ("surface", 1), ("created_at", -1)]),
            "surface",
            "request_id",
            "created_at",
        ]
