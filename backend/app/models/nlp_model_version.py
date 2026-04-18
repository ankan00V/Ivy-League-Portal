from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class NLPModelVersion(Document):
    name: str = "nlp-model-v1"
    is_active: bool = Field(default=False, index=True)
    intent_labels: list[str] = Field(default_factory=list)
    intent_centroids: dict[str, list[float]] = Field(default_factory=dict)
    intent_classifier_head: dict[str, Any] = Field(default_factory=dict)
    entity_lexicon: dict[str, list[str]] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    baseline_confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    evaluation_snapshot: dict[str, Any] = Field(default_factory=dict)
    training_rows: int = 0
    split_summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "nlp_model_versions"
        indexes = [
            "is_active",
            "created_at",
            "updated_at",
        ]
