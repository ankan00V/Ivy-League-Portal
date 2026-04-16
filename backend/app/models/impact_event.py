from datetime import datetime
from typing import Literal, Optional

from beanie import Document
from pydantic import Field


ImpactEventType = Literal[
    "view_opportunity",
    "shortlist_opportunity",
    "start_application",
    "submit_application",
    "interview_scheduled",
    "offer_received",
]


class ImpactEvent(Document):
    user_id: str = Field(index=True)
    opportunity_id: Optional[str] = Field(default=None, index=True)
    event_type: ImpactEventType = Field(index=True)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "impact_events"
        indexes = ["user_id", "event_type", "created_at", "opportunity_id"]
