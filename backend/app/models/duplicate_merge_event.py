from __future__ import annotations

from datetime import datetime
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.time import utc_now


class DuplicateMergeEvent(Document):
    canonical_opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    duplicate_opportunity_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    canonical_source: str = Field(default="unknown", json_schema_extra={"index": True})
    duplicate_source: str = Field(default="unknown", json_schema_extra={"index": True})
    canonical_source_id: Optional[str] = None
    duplicate_source_id: Optional[str] = None
    canonical_url: Optional[str] = None
    duplicate_url: Optional[str] = None
    stage: str = Field(json_schema_extra={"index": True})
    score: float = 1.0
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "duplicate_merge_events"
        indexes = [
            "canonical_opportunity_id",
            "duplicate_opportunity_id",
            "canonical_source",
            "duplicate_source",
            "stage",
            "created_at",
            [("canonical_source", 1), ("duplicate_source", 1), ("created_at", -1)],
            [("canonical_opportunity_id", 1), ("created_at", -1)],
        ]
