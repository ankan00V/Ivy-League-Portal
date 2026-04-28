from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field


class VectorIndexEntry(Document):
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True, "unique": True})
    text_hash: str = Field(json_schema_extra={"index": True})
    text: str = ""
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "vector_index_entries"
        indexes = [
            "opportunity_id",
            "text_hash",
            "updated_at",
        ]

