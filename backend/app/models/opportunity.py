from typing import Optional
from datetime import datetime
from app.core.time import utc_now
from beanie import Document, PydanticObjectId
from pydantic import Field

class Opportunity(Document):
    title: str = Field(json_schema_extra={"index": True})
    description: str
    url: str = Field(json_schema_extra={"unique": True})
    opportunity_type: Optional[str] = None
    portal_category: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    domain: Optional[str] = None
    university: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    eligibility: Optional[str] = None
    ppo_available: Optional[str] = None
    is_employer_post: bool = False
    posted_by_user_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    lifecycle_status: str = Field(default="published", json_schema_extra={"index": True})  # draft | published | paused | closed
    published_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    lifecycle_updated_at: datetime = Field(default_factory=utc_now)
    duration_start: Optional[datetime] = None
    duration_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "opportunities"
        indexes = [
            "domain",
            "opportunity_type",
            "portal_category",
            "university",
            "source",
            "ppo_available",
            "duration_start",
            "duration_end",
            "deadline",
            "last_seen_at",
            "posted_by_user_id",
            "lifecycle_status",
            "published_at",
            "paused_at",
            "closed_at",
            "lifecycle_updated_at",
        ]
