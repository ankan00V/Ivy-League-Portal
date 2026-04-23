from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document
from pydantic import Field


RAGEvaluationMode = Literal["offline", "online"]


class RAGTemplateEvaluationRun(Document):
    template_key: str = Field(default="ask_ai", min_length=1, index=True)
    template_label: str = Field(min_length=1, index=True)
    template_version_id: str = Field(min_length=1, index=True)
    mode: RAGEvaluationMode = Field(index=True)
    metrics: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    accepted: bool = Field(default=False, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
