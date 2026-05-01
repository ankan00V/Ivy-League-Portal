from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field

from app.core.time import utc_now


class ModelArtifactVersion(Document):
    model_family: str = Field(default="learned_ranker")
    model_version_id: Optional[str] = None
    artifact_uri: str = Field(min_length=1)
    storage_provider: str = Field(default="file")
    checksum_sha256: Optional[str] = None
    local_cache_path: Optional[str] = None
    feature_schema: dict[str, Any] = Field(default_factory=dict)
    training_metadata: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="registered")
    verified: bool = False
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    promoted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "model_artifact_versions"
        indexes = [
            "model_family",
            "model_version_id",
            "artifact_uri",
            "storage_provider",
            "checksum_sha256",
            "status",
            "created_at",
        ]
