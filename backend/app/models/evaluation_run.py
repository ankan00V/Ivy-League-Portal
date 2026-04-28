from datetime import datetime
from app.core.time import utc_now
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class EvaluationRun(Document):
    evaluator: str = "retrieval-quality-v1"
    dataset_size: int
    top_k: int
    metrics: dict[str, float]
    details: list[dict[str, Any]] = Field(default_factory=list)
    created_by_user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "evaluation_runs"
        indexes = ["created_at", "evaluator"]
