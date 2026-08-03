from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

from app.core.time import utc_now
from app.models.traffic import TrafficType


FeedbackReason = Literal[
    "too_far",
    "wrong_skills",
    "already_applied",
    "too_low_stipend",
    "not_interested",
    "spam",
]
CareerOutcomeStage = Literal[
    "application_submitted",
    "interview_scheduled",
    "offer_received",
    "offer_accepted",
    "joined",
    "retained_6_months",
]


class RecommendationSession(Document):
    """Coarse, privacy-preserving context for a recommendation visit."""

    session_id: str = Field(min_length=1, json_schema_extra={"index": True})
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    started_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    last_activity_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    ended_at: Optional[datetime] = None
    device_type: str = Field(default="unknown", max_length=32)
    platform: str = Field(default="web", max_length=32)
    country_code: Optional[str] = Field(default=None, max_length=8)
    network_type: str = Field(default="unknown", max_length=32)
    logged_in: bool = True
    total_results: int = Field(default=0, ge=0)
    query: Optional[str] = Field(default=None, max_length=500)
    sort: Optional[str] = Field(default=None, max_length=80)
    filters: dict[str, Any] = Field(default_factory=dict)
    entry_source: str = Field(default="unknown", max_length=80)
    previous_session_gap_seconds: Optional[int] = Field(default=None, ge=0)
    experiment_key: Optional[str] = Field(default=None, max_length=120)
    experiment_variant: Optional[str] = Field(default=None, max_length=120)
    traffic_type: TrafficType = Field(default="real", json_schema_extra={"index": True})
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "recommendation_sessions"
        indexes = [
            IndexModel([("session_id", 1)], unique=True),
            "user_id",
            "started_at",
            "last_activity_at",
            "traffic_type",
            IndexModel([("user_id", 1), ("last_activity_at", -1)]),
        ]


class OpportunityVersion(Document):
    """Immutable opportunity state used by an exposure or downstream label."""

    version_id: str = Field(min_length=1, json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    version_number: int = Field(ge=1)
    content_hash: str = Field(min_length=16, json_schema_extra={"index": True})
    snapshot: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "opportunity_versions"
        indexes = [
            IndexModel([("version_id", 1)], unique=True),
            IndexModel([("opportunity_id", 1), ("content_hash", 1)], unique=True),
            IndexModel([("opportunity_id", 1), ("version_number", -1)]),
        ]


class RecommendationFeatureSnapshot(Document):
    """Frozen model inputs so offline training matches the served ranking."""

    snapshot_id: str = Field(min_length=1, json_schema_extra={"index": True})
    snapshot_hash: str = Field(min_length=16, json_schema_extra={"index": True})
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    feature_schema_version: str = Field(default="ranker-features-v3", max_length=120)
    model_version_id: Optional[str] = Field(default=None, max_length=160)
    profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    opportunity_snapshot: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "recommendation_feature_snapshots"
        indexes = [
            IndexModel([("snapshot_id", 1)], unique=True),
            IndexModel([("snapshot_hash", 1)], unique=True),
            "user_id",
            "opportunity_id",
            "opportunity_version_id",
            "captured_at",
        ]


class RecommendationExposure(Document):
    """One immutable ranked opportunity exposure, independent of later clicks."""

    exposure_id: str = Field(min_length=1, json_schema_extra={"index": True})
    session_id: str = Field(min_length=1, json_schema_extra={"index": True})
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_version_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    feature_snapshot_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    ranking_mode: Optional[str] = Field(default=None, max_length=32)
    experiment_key: Optional[str] = Field(default=None, max_length=120)
    experiment_variant: Optional[str] = Field(default=None, max_length=120)
    model_version_id: Optional[str] = Field(default=None, max_length=160)
    rank_position: int = Field(ge=1)
    match_score: Optional[float] = None
    randomized_exposure: bool = False
    exploration_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    query: Optional[str] = Field(default=None, max_length=500)
    filter_fingerprint: Optional[str] = Field(default=None, max_length=128)
    traffic_type: TrafficType = Field(default="real", json_schema_extra={"index": True})
    served_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "recommendation_exposures"
        indexes = [
            IndexModel([("exposure_id", 1)], unique=True),
            "session_id",
            "user_id",
            "opportunity_id",
            "feature_snapshot_id",
            "traffic_type",
            "served_at",
            IndexModel([("user_id", 1), ("opportunity_id", 1), ("served_at", -1)]),
            IndexModel([("session_id", 1), ("rank_position", 1)]),
        ]


class RecommendationFeedback(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    exposure_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    reason: FeedbackReason
    comment: Optional[str] = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "recommendation_feedback"
        indexes = ["user_id", "opportunity_id", "exposure_id", "reason", "created_at"]


class CareerOutcomeEvent(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    opportunity_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    application_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    exposure_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    stage: CareerOutcomeStage
    occurred_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    user_confirmed: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "career_outcome_events"
        indexes = [
            "user_id",
            "opportunity_id",
            "application_id",
            "exposure_id",
            "stage",
            "occurred_at",
            IndexModel([("user_id", 1), ("occurred_at", -1)]),
        ]
