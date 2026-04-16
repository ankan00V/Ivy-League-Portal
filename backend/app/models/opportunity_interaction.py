from datetime import datetime
from typing import Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

InteractionType = Literal["impression", "view", "click", "apply"]
RankingMode = Literal["baseline", "semantic", "ab"]


class OpportunityInteraction(Document):
    user_id: PydanticObjectId = Field(index=True)
    opportunity_id: PydanticObjectId = Field(index=True)
    interaction_type: InteractionType = "view"
    ranking_mode: Optional[RankingMode] = None
    query: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "opportunity_interactions"
        indexes = [
            "user_id",
            "opportunity_id",
            "interaction_type",
            "ranking_mode",
            "created_at",
        ]
