from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Literal, Optional

from beanie import Document, Indexed
from pydantic import Field
from pymongo import IndexModel


RAGTemplateStatus = Literal["draft", "active", "archived"]


class RAGTemplateVersion(Document):
    template_key: str = Field(default="ask_ai", min_length=1, json_schema_extra={"index": True})
    label: Indexed(str, unique=True)  # type: ignore[valid-type]
    version: int = Field(ge=1, json_schema_extra={"index": True})
    description: Optional[str] = None
    status: RAGTemplateStatus = "draft"
    is_active: bool = Field(default=False, json_schema_extra={"index": True})
    is_online_candidate: bool = Field(default=False, json_schema_extra={"index": True})
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = Field(min_length=20)
    judge_rubric: str = Field(min_length=20)
    acceptance_thresholds: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "rag_template_versions"
        indexes = [
            IndexModel([("template_key", 1), ("version", 1)], unique=True),
            "template_key",
            "label",
            "version",
            "status",
            "is_active",
            "is_online_candidate",
            "created_at",
            "updated_at",
        ]
