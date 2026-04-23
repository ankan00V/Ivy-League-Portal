from typing import Optional
from datetime import datetime
from beanie import Document, PydanticObjectId
from pydantic import Field

class Application(Document):
    user_id: PydanticObjectId
    opportunity_id: PydanticObjectId
    status: str = "Pending"
    pipeline_state: str = Field(default="applied", index=True)  # applied | shortlisted | rejected | interview
    pipeline_notes: Optional[str] = None
    pipeline_updated_at: datetime = Field(default_factory=datetime.utcnow)
    pipeline_updated_by: Optional[PydanticObjectId] = Field(default=None, index=True)
    resume_snapshot: Optional[str] = None
    automation_mode: Optional[str] = None
    automation_log: Optional[str] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "applications"
        indexes = ["user_id", "opportunity_id", "pipeline_state", "pipeline_updated_at", "pipeline_updated_by"]
