from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.models.traffic import TrafficType

InteractionType = Literal["impression", "view", "click", "apply", "save"]
RankingMode = Literal["baseline", "semantic", "ml", "ab"]


class OpportunityInteraction(Document):
    user_id: PydanticObjectId = Field(index=True)
    opportunity_id: PydanticObjectId = Field(index=True)
    interaction_type: InteractionType = "view"
    ranking_mode: Optional[RankingMode] = None
    experiment_key: Optional[str] = Field(default=None, index=True)
    experiment_variant: Optional[str] = Field(default=None, index=True)
    query: Optional[str] = None
    model_version_id: Optional[str] = Field(default=None, index=True)
    rank_position: Optional[int] = None
    match_score: Optional[float] = None
    features: Optional[dict[str, Any]] = None
    traffic_type: TrafficType = Field(default="real", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "opportunity_interactions"
        indexes = [
            "user_id",
            "opportunity_id",
            "interaction_type",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "model_version_id",
            "traffic_type",
            "created_at",
        ]
