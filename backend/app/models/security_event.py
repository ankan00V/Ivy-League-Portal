from __future__ import annotations

from datetime import datetime
from typing import Any

from beanie import Document
from pydantic import Field

from app.core.time import utc_now


class SecurityEvent(Document):
    event_type: str = Field(default="csp_violation")
    source: str = Field(default="frontend")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "security_events"
        indexes = [
            "event_type",
            "source",
            "created_at",
        ]
