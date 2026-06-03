from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse

from beanie import Document, PydanticObjectId
from pydantic import Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.time import utc_now


class DiscoveryMethod(str, Enum):
    web_search = "web_search"
    company_seed = "company_seed"
    careers_link_crawl = "careers_link_crawl"
    user_submission = "user_submission"
    similar_source_expansion = "similar_source_expansion"
    admin_manual = "admin_manual"
    employer_claim = "employer_claim"


class SourceStatus(str, Enum):
    discovered = "discovered"
    qualifying = "qualifying"
    qualified = "qualified"
    extracting = "extracting"
    probation = "probation"
    promoted = "promoted"
    rejected = "rejected"
    quarantined = "quarantined"
    paused = "paused"


class ScraperRegistrationStatus(str, Enum):
    active = "active"
    paused = "paused"
    quarantined = "quarantined"


def _validate_http_url(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")
    return candidate


def _normalize_domain(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return candidate
    if "://" in candidate:
        candidate = urlparse(candidate).netloc
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate.strip(".")


class DiscoveredSource(Document):
    url: str
    domain: str
    name: Optional[str] = None
    source_type: Optional[str] = None

    discovery_method: DiscoveryMethod
    discovery_query: Optional[str] = None
    discovered_at: datetime = Field(default_factory=utc_now)
    discovered_by: Optional[str] = None

    status: SourceStatus = SourceStatus.discovered
    qualification_score: Optional[float] = Field(default=None, ge=0, le=100)
    qualification_details: Optional[dict[str, Any]] = None
    qualified_at: Optional[datetime] = None

    extraction_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    parser_template: Optional[dict[str, Any]] = None
    sample_opportunities: Optional[list[dict[str, Any]]] = None
    extraction_model_version: Optional[str] = None
    extracted_at: Optional[datetime] = None

    trust_score: Optional[float] = Field(default=None, ge=0, le=100)
    trust_breakdown: Optional[dict[str, Any]] = None
    trust_score_boost: float = Field(default=0.0, ge=0, le=30)

    probation_start: Optional[datetime] = None
    probation_runs: int = Field(default=0, ge=0)
    probation_items_fetched: list[int] = Field(default_factory=list)
    probation_items_passed_quality: list[int] = Field(default_factory=list)
    probation_parse_rates: list[float] = Field(default_factory=list)
    probation_failures: list[str] = Field(default_factory=list)

    promoted_at: Optional[datetime] = None
    promoted_by: Optional[str] = None
    scraper_key: Optional[str] = None
    total_opportunities_contributed: int = Field(default=0, ge=0)

    rejection_reason: Optional[str] = None
    rejected_at: Optional[datetime] = None
    retry_after: Optional[datetime] = None

    admin_notes: Optional[str] = None
    requires_admin_review: bool = False
    admin_hold: bool = False
    admin_reviewed_by: Optional[str] = None
    admin_reviewed_at: Optional[datetime] = None

    consecutive_failures: int = Field(default=0, ge=0)
    health_score: float = Field(default=100.0, ge=0, le=100)
    last_scraped_at: Optional[datetime] = None
    last_health_reason: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = _validate_http_url(value, field_name="url")
        if normalized is None:
            raise ValueError("url is required")
        return normalized

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        normalized = _normalize_domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("domain must be a valid host")
        return normalized

    class Settings:
        name = "discovered_sources"
        indexes = [
            IndexModel([("domain", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("trust_score", DESCENDING)]),
            IndexModel([("discovered_at", DESCENDING)]),
            IndexModel([("source_type", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("discovered_by", ASCENDING), ("discovered_at", DESCENDING)]),
        ]


class CompanySeed(Document):
    company_name: str
    domain: str
    careers_url: Optional[str] = None
    industry: str
    company_size: str
    india_presence: bool = True
    student_friendly: bool = True
    added_by: str = "system"
    discovered_source_id: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("domain")
    @classmethod
    def validate_seed_domain(cls, value: str) -> str:
        normalized = _normalize_domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("domain must be a valid host")
        return normalized

    @field_validator("careers_url")
    @classmethod
    def validate_careers_url(cls, value: str | None) -> str | None:
        return _validate_http_url(value, field_name="careers_url")

    class Settings:
        name = "company_seeds"
        indexes = [
            IndexModel([("domain", ASCENDING)], unique=True),
            IndexModel([("india_presence", ASCENDING), ("student_friendly", ASCENDING)]),
            IndexModel([("discovered_source_id", ASCENDING)]),
        ]


class SourceDiscoveryRun(Document):
    run_id: str
    triggered_by: str
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    status: str = "running"

    queries_executed: int = Field(default=0, ge=0)
    urls_discovered: int = Field(default=0, ge=0)
    urls_already_known: int = Field(default=0, ge=0)
    urls_queued_for_qualification: int = Field(default=0, ge=0)

    qualified: int = Field(default=0, ge=0)
    failed_qualification: int = Field(default=0, ge=0)
    extracted: int = Field(default=0, ge=0)
    failed_extraction: int = Field(default=0, ge=0)
    promoted: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)

    errors: list[str] = Field(default_factory=list)

    class Settings:
        name = "source_discovery_runs"
        indexes = [
            IndexModel([("run_id", ASCENDING)], unique=True),
            IndexModel([("started_at", DESCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]


class BadDomainEntry(Document):
    domain: str
    reason: str
    added_at: datetime = Field(default_factory=utc_now)
    added_by: str

    @field_validator("domain")
    @classmethod
    def validate_bad_domain(cls, value: str) -> str:
        normalized = _normalize_domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("domain must be a valid host")
        return normalized

    class Settings:
        name = "bad_domain_list"
        indexes = [IndexModel([("domain", ASCENDING)], unique=True)]


class ProbationOpportunity(Document):
    discovered_source_id: PydanticObjectId
    scraper_key: Optional[str] = None
    title: str
    company: Optional[str] = None
    url: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    quality_score: float = Field(default=0.0, ge=0, le=100)
    run_number: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("url")
    @classmethod
    def validate_probation_url(cls, value: str) -> str:
        normalized = _validate_http_url(value, field_name="url")
        if normalized is None:
            raise ValueError("url is required")
        return normalized

    class Settings:
        name = "probation_opportunities"
        indexes = [
            IndexModel([("discovered_source_id", ASCENDING), ("run_number", ASCENDING)]),
            IndexModel([("url", ASCENDING)]),
        ]


class ScraperRegistration(Document):
    scraper_key: str
    source_name: str
    domain: str
    careers_url: str
    source_type: Optional[str] = None
    extraction_method: str = "llm_css"
    parser_template: dict[str, Any] = Field(default_factory=dict)
    trust_score: float = Field(default=0.0, ge=0, le=100)
    status: ScraperRegistrationStatus = ScraperRegistrationStatus.active
    schedule: str = "every_6_hours"
    last_scraped_at: Optional[datetime] = None
    health_score: float = Field(default=100.0, ge=0, le=100)
    total_yield: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    stale_template_failures: int = Field(default=0, ge=0)
    discovered_source_id: Optional[str] = None
    is_original_source: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("careers_url")
    @classmethod
    def validate_registration_url(cls, value: str) -> str:
        normalized = _validate_http_url(value, field_name="careers_url")
        if normalized is None:
            raise ValueError("careers_url is required")
        return normalized

    @field_validator("domain")
    @classmethod
    def validate_registration_domain(cls, value: str) -> str:
        normalized = _normalize_domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("domain must be a valid host")
        return normalized

    class Settings:
        name = "scraper_registrations"
        indexes = [
            IndexModel([("scraper_key", ASCENDING)], unique=True),
            IndexModel([("domain", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("discovered_source_id", ASCENDING)]),
        ]


class DiscoveryLLMCall(Document):
    domain: str
    method: str
    model: Optional[str] = None
    tokens_used: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    cost_estimate_usd: float = Field(default=0.0, ge=0)
    success: bool = True
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "discovery_llm_calls"
        indexes = [
            IndexModel([("domain", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]


class EmployerCareersClaim(Document):
    employer_user_id: PydanticObjectId
    company_name: str
    company_domain: str
    careers_url: str
    verification_token: str
    verification_status: str = "pending"
    discovered_source_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    verified_at: Optional[datetime] = None

    @field_validator("careers_url")
    @classmethod
    def validate_claim_url(cls, value: str) -> str:
        normalized = _validate_http_url(value, field_name="careers_url")
        if normalized is None:
            raise ValueError("careers_url is required")
        return normalized

    @field_validator("company_domain")
    @classmethod
    def validate_claim_domain(cls, value: str) -> str:
        normalized = _normalize_domain(value)
        if not normalized or "." not in normalized:
            raise ValueError("company_domain must be a valid host")
        return normalized

    class Settings:
        name = "employer_careers_claims"
        indexes = [
            IndexModel([("employer_user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("verification_token", ASCENDING)], unique=True),
            IndexModel([("company_domain", ASCENDING)]),
        ]


SOURCE_DISCOVERY_DOCUMENTS = [
    DiscoveredSource,
    CompanySeed,
    SourceDiscoveryRun,
    BadDomainEntry,
    ProbationOpportunity,
    ScraperRegistration,
    DiscoveryLLMCall,
    EmployerCareersClaim,
]


async def create_indexes() -> None:
    for model in SOURCE_DISCOVERY_DOCUMENTS:
        settings = getattr(model, "Settings", None)
        indexes = list(getattr(settings, "indexes", []) or [])
        index_models = [index for index in indexes if isinstance(index, IndexModel)]
        if index_models:
            collection_getter = getattr(model, "get_motor_collection", None) or getattr(model, "get_pymongo_collection")
            await collection_getter().create_indexes(index_models)
