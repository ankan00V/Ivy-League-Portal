from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.models.traffic import TrafficType
from app.core.time import utc_now

InteractionType = Literal[
    "impression",
    "view",
    "click",
    "expand",
    "save",
    "apply",
    "apply_start",
    "apply_complete",
    "share",
    "skip",
    "dismiss",
    "shortlisted",
    "interview",
    "rejected",
]
RankingMode = Literal["baseline", "semantic", "ml", "ab", "diversity"]


class OpportunityInteraction(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    interaction_type: InteractionType = "view"
    event_type: Optional[InteractionType] = Field(default=None, json_schema_extra={"index": True})
    reward: float = Field(default=0.0, ge=-1.0, le=1.0, json_schema_extra={"index": True})
    dwell_time_ms: Optional[int] = Field(default=None, ge=0)
    scroll_depth: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    referrer_rank: Optional[int] = Field(default=None, ge=1)
    session_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    cold_start: bool = Field(default=False, json_schema_extra={"index": True})
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
            "event_type",
            "session_id",
            "cold_start",
            "reward",
            "ranking_mode",
            "experiment_key",
            "experiment_variant",
            "model_version_id",
            "traffic_type",
            "created_at",
            IndexModel([("traffic_type", 1), ("created_at", -1)]),
            IndexModel([("user_id", 1), ("created_at", -1)]),
            IndexModel([("opportunity_id", 1), ("created_at", -1)]),
            IndexModel([("experiment_key", 1), ("experiment_variant", 1), ("traffic_type", 1), ("created_at", -1)]),
            IndexModel([("event_type", 1), ("created_at", -1)]),
        ]
