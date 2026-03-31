from typing import Optional
from datetime import datetime
from beanie import Document, PydanticObjectId
from pydantic import Field

class Application(Document):
    user_id: PydanticObjectId
    opportunity_id: PydanticObjectId
    status: str = "Pending"
    resume_snapshot: Optional[str] = None
    automation_mode: Optional[str] = None
    automation_log: Optional[str] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "applications"
        indexes = ["user_id", "opportunity_id"]
