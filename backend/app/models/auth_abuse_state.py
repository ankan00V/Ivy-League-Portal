from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AuthAbuseState(Document):
    key: str = Field(min_length=1)
    email: str = Field(json_schema_extra={"index": True}, min_length=3)
    action: str = Field(json_schema_extra={"index": True}, min_length=1)
    purpose: str = Field(json_schema_extra={"index": True}, min_length=1)
    failed_attempts: int = Field(default=0, ge=0)
    first_failed_at: datetime = Field(default_factory=utc_now)
    last_failed_at: datetime = Field(default_factory=utc_now)
    lock_until: datetime | None = Field(default=None, json_schema_extra={"index": True})
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "auth_abuse_states"
        indexes = [
            IndexModel([("key", 1)], unique=True),
            "email",
            "action",
            "purpose",
            "lock_until",
            "updated_at",
        ]
