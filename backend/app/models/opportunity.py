from typing import Optional
from datetime import datetime
from beanie import Document, PydanticObjectId
from pydantic import Field

class Opportunity(Document):
    title: str = Field(index=True)
    description: str
    url: str = Field(unique=True)
    opportunity_type: Optional[str] = None
    domain: Optional[str] = None
    university: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    eligibility: Optional[str] = None
    is_employer_post: bool = False
    posted_by_user_id: Optional[PydanticObjectId] = Field(default=None, index=True)
    lifecycle_status: str = Field(default="published", index=True)  # draft | published | paused | closed
    published_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    lifecycle_updated_at: datetime = Field(default_factory=datetime.utcnow)
    deadline: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "opportunities"
        indexes = [
            "domain",
            "opportunity_type",
            "university",
            "source",
            "deadline",
            "last_seen_at",
            "posted_by_user_id",
            "lifecycle_status",
            "published_at",
            "paused_at",
            "closed_at",
            "lifecycle_updated_at",
        ]
