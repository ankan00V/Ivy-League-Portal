from typing import Optional
from datetime import datetime
from beanie import Document
from pydantic import Field

class Opportunity(Document):
    title: str = Field(index=True)
    description: str
    url: str = Field(unique=True)
    opportunity_type: Optional[str] = None
    domain: Optional[str] = None
    university: Optional[str] = None
    source: Optional[str] = None
    deadline: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "opportunities"
        indexes = ["domain", "opportunity_type", "university", "source", "deadline", "last_seen_at"]
