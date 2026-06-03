from typing import Optional
from datetime import datetime
from app.core.time import utc_now
from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel

class Opportunity(Document):
    title: str = Field(json_schema_extra={"index": True})
    description: str
    url: str = Field(json_schema_extra={"unique": True})
    canonical_url_hash: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    canonical_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    title_company_location_hash: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    duplicate_cluster_key: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    normalized_title: Optional[str] = None
    normalized_organization: Optional[str] = None
    opportunity_type: Optional[str] = None
    portal_category: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    domain: Optional[str] = None
    university: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    seen_on: list[str] = Field(default_factory=list)
    source_count: int = Field(default=1, ge=1)
    source_ids: dict[str, list[str]] = Field(default_factory=dict)
    duplicate_count: int = Field(default=0, ge=0)
    dedup_score: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_last_merged_at: Optional[datetime] = None
    location: Optional[str] = None
    work_mode: Optional[str] = None
    stipend: Optional[str] = None
    eligibility: Optional[str] = None
    batch_years: list[int] = Field(default_factory=list)
    ppo_available: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    quality_score: Optional[float] = Field(default=None, ge=0.0, le=100.0, json_schema_extra={"index": True})
    quality_missing_fields: list[str] = Field(default_factory=list)
    last_quality_run_at: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    embedding: list[float] = Field(default_factory=list)
    embedding_text_hash: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    embedding_model_version: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    embedding_updated_at: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    stipend_min: Optional[int] = Field(default=None, ge=0)
    stipend_max: Optional[int] = Field(default=None, ge=0)
    stipend_currency: Optional[str] = None
    stipend_period: Optional[str] = None
    duration_months: Optional[float] = Field(default=None, ge=0.0)
    trust_status: str = Field(default="unreviewed", json_schema_extra={"index": True})  # verified | unreviewed | needs_review | blocked
    trust_score: int = Field(default=50, ge=0, le=100)
    risk_score: int = Field(default=50, ge=0, le=100)
    risk_reasons: list[str] = Field(default_factory=list)
    verification_evidence: list[str] = Field(default_factory=list)
    reviewed_by_user_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    reviewed_at: Optional[datetime] = None
    is_employer_post: bool = False
    posted_by_user_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    lifecycle_status: str = Field(default="published", json_schema_extra={"index": True})  # draft | published | paused | closed
    opportunity_status: str = Field(default="active", json_schema_extra={"index": True})  # active | closing_soon | expired | filled | removed
    freshness_score: float = Field(default=1.0, ge=0.0, le=1.0, json_schema_extra={"index": True})
    url_liveness_status: str = Field(default="unknown", json_schema_extra={"index": True})  # unknown | alive | dead | error
    url_last_checked_at: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    published_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    lifecycle_updated_at: datetime = Field(default_factory=utc_now)
    duration_start: Optional[datetime] = None
    duration_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "opportunities"
        indexes = [
            "domain",
            "opportunity_type",
            "portal_category",
            "canonical_url_hash",
            "canonical_key",
            "title_company_location_hash",
            "duplicate_cluster_key",
            "university",
            "source",
            "source_id",
            "seen_on",
            "source_count",
            "location",
            "work_mode",
            "stipend",
            "tags",
            "quality_score",
            "last_quality_run_at",
            "embedding_text_hash",
            "embedding_model_version",
            "embedding_updated_at",
            "batch_years",
            "ppo_available",
            "trust_status",
            "risk_score",
            "reviewed_by_user_id",
            "reviewed_at",
            "duration_start",
            "duration_end",
            "deadline",
            "last_seen_at",
            "posted_by_user_id",
            "lifecycle_status",
            "opportunity_status",
            "freshness_score",
            "url_liveness_status",
            "url_last_checked_at",
            "published_at",
            "paused_at",
            "closed_at",
            "lifecycle_updated_at",
            IndexModel([("lifecycle_status", 1), ("last_seen_at", -1)]),
            IndexModel([("opportunity_status", 1), ("freshness_score", -1), ("last_seen_at", -1)]),
            IndexModel([("quality_score", -1), ("last_seen_at", -1)]),
            IndexModel([("source", 1), ("last_seen_at", -1)]),
            IndexModel([("embedding_model_version", 1), ("embedding_updated_at", 1)]),
            IndexModel([("trust_status", 1), ("risk_score", 1), ("updated_at", -1)]),
        ]
