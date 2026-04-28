from datetime import datetime
from app.core.time import utc_now
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
    user_id: str = Field(json_schema_extra={"index": True})
    opportunity_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    event_type: ImpactEventType = Field(json_schema_extra={"index": True})
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "impact_events"
        indexes = ["user_id", "event_type", "created_at", "opportunity_id"]
