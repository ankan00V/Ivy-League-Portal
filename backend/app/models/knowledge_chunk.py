from datetime import datetime
from app.core.time import utc_now
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class KnowledgeChunk(Document):
    source_type: Indexed(str)
    source_id: Indexed(str)
    source_url: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    chunk_text: str
    embedding: list[float]
    embedding_model: str = "hashing-v1"
    chunk_index: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "knowledge_chunks"
        indexes = [
            "source_type",
            "source_id",
            "domain",
            "updated_at",
            [("source_type", 1), ("source_id", 1), ("chunk_index", 1)],
        ]
