from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.core.time import utc_now

OutcomePromptType = Literal["match_quality", "heard_back"]
OutcomeResponse = Literal["yes", "no", "somewhat", "still_waiting"]


class ApplicationOutcome(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    application_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    interaction_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    prompt_type: OutcomePromptType = Field(json_schema_extra={"index": True})
    response: OutcomeResponse
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "application_outcomes"
        indexes = [
            "user_id",
            "opportunity_id",
            "application_id",
            "interaction_id",
            "prompt_type",
            "created_at",
            [("user_id", 1), ("opportunity_id", 1), ("prompt_type", 1)],
        ]
