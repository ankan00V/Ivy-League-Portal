from __future__ import annotations

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel


class AskAISavedQuery(Document):
    user_id: PydanticObjectId = Field(index=True)
    surface: str = Field(default="opportunities_page", min_length=1, index=True)
    query: str = Field(min_length=2)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Settings:
        name = "ask_ai_saved_queries"
        indexes = [
            IndexModel([("user_id", 1), ("surface", 1), ("query", 1)], unique=True),
            IndexModel([("user_id", 1), ("surface", 1), ("last_used_at", -1)]),
            "user_id",
            "surface",
            "last_used_at",
        ]
