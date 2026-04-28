from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field

from app.models.traffic import TrafficType
from app.core.time import utc_now

InteractionType = Literal["impression", "view", "click", "apply", "save"]
RankingMode = Literal["baseline", "semantic", "ml", "ab"]


class OpportunityInteraction(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    interaction_type: InteractionType = "view"
    ranking_mode: Optional[RankingMode] = None
    experiment_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    experiment_variant: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    query: Optional[str] = None
    model_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    rank_position: Optional[int] = None
    match_score: Optional[float] = None
    features: Optional[dict[str, Any]] = None
    traffic_type: TrafficType = Field(default="real", json_schema_extra={"index": True})
    created_at: datetime = Field(default_factory=utc_now)

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
