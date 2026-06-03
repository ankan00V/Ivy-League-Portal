from __future__ import annotations

from datetime import datetime
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.time import utc_now


class UserJourney(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    session_id: str = Field(json_schema_extra={"index": True})
    started_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    ended_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    event_count: int = Field(default=0, ge=0)
    opportunity_ids: list[PydanticObjectId] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    path: list[dict[str, Any]] = Field(default_factory=list)
    pogo_sticking_count: int = Field(default=0, ge=0)
    reward_sum: float = 0.0
    cold_start: bool = False
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "user_journeys"
        indexes = [
            "user_id",
            "session_id",
            "started_at",
            "ended_at",
            "cold_start",
            [("user_id", 1), ("ended_at", -1)],
            [("user_id", 1), ("session_id", 1)],
        ]
