from __future__ import annotations

from datetime import datetime
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class AuthAuditEvent(Document):
    event_type: str = Field(index=True, min_length=1)
    email: Optional[str] = Field(default=None, index=True)
    account_type: Optional[str] = Field(default=None, index=True)
    purpose: Optional[str] = Field(default=None, index=True)
    success: bool = Field(default=False, index=True)
    reason: Optional[str] = None
    ip_address: Optional[str] = Field(default=None, index=True)
    user_agent: Optional[str] = None
    user_id: Optional[PydanticObjectId] = Field(default=None, index=True)
    lock_applied: bool = Field(default=False, index=True)
    lock_until: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "auth_audit_events"
        indexes = [
            "event_type",
            "email",
            "account_type",
            "purpose",
            "success",
            "ip_address",
            "user_id",
            "lock_applied",
            "lock_until",
            "created_at",
        ]
