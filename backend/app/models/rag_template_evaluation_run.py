from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Any, Literal, Optional

from beanie import Document
from pydantic import Field


RAGEvaluationMode = Literal["offline", "online"]


class RAGTemplateEvaluationRun(Document):
    template_key: str = Field(default="ask_ai", min_length=1, json_schema_extra={"index": True})
    template_label: str = Field(min_length=1, json_schema_extra={"index": True})
    template_version_id: str = Field(min_length=1, json_schema_extra={"index": True})
    mode: RAGEvaluationMode = Field(json_schema_extra={"index": True})
    metrics: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    accepted: bool = Field(default=False, json_schema_extra={"index": True})
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "rag_template_evaluation_runs"
        indexes = [
            "template_key",
            "template_label",
            "template_version_id",
            "mode",
            "accepted",
            "created_at",
        ]
