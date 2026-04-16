from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field


class BackgroundJob(Document):
    job_type: str = Field(index=True)
    payload: dict[str, Any] = Field(default_factory=dict)

    status: str = Field(default="pending", index=True)  # pending|running|succeeded|retry|dead
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=5)

    run_after: datetime = Field(default_factory=datetime.utcnow, index=True)
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = Field(default=None, index=True)

    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None

    result: Optional[dict[str, Any]] = None

    dedupe_key: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    class Settings:
        name = "background_jobs"
        indexes = [
            "status",
            "run_after",
            "locked_at",
            "job_type",
            "dedupe_key",
            "created_at",
        ]

