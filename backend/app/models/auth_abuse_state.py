from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AuthAbuseState(Document):
    key: str = Field(min_length=1)
    email: str = Field(index=True, min_length=3)
    action: str = Field(index=True, min_length=1)
    purpose: str = Field(index=True, min_length=1)
    failed_attempts: int = Field(default=0, ge=0)
    first_failed_at: datetime = Field(default_factory=datetime.utcnow)
    last_failed_at: datetime = Field(default_factory=datetime.utcnow)
    lock_until: datetime | None = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
