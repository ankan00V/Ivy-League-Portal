from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field, field_validator
from pymongo import IndexModel

class Profile(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"unique": True})
    account_type: str = "candidate"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    country_code: str = "+91"
    user_type: Optional[str] = None  # school_student | college_student | fresher | professional
    domain: Optional[str] = None
    course: Optional[str] = None
    course_specialization: Optional[str] = None
    passout_year: Optional[int] = None
    class_grade: Optional[int] = None
    current_job_role: Optional[str] = None
    total_work_experience: Optional[str] = None
    experience_summary: Optional[str] = None
    college_name: Optional[str] = None
    company_name: Optional[str] = None
    company_website: Optional[str] = None
    company_size: Optional[str] = None
    company_description: Optional[str] = None
    hiring_for: Optional[str] = None  # myself | others
    goals: list[str] = Field(default_factory=list)
    career_intent: list[str] = Field(default_factory=list)
    domains_of_interest: list[str] = Field(default_factory=list)
    preferred_roles: Optional[str] = None
    preferred_locations: Optional[str] = None
    preferred_work_mode: Optional[str] = None
    work_preferences: list[str] = Field(default_factory=list)
    expected_stipend_range: Optional[str] = None
    expected_stipend_min: Optional[int] = Field(default=None, ge=0)
    expected_stipend_max: Optional[int] = Field(default=None, ge=0)
    availability: Optional[str] = None
    graduation_year: Optional[int] = None
    opportunity_types: list[str] = Field(default_factory=list)
    pan_india: bool = False
    prefer_wfh: bool = False
    consent_data_processing: bool = False
    consent_updates: bool = False
    # When consent was granted, which policy text it was granted against, and when
    # it was withdrawn. Without these the flag is unauditable: a bare boolean cannot
    # say whether a student agreed to the policy we publish today or to something
    # replaced since. See `services/privacy_consent_service.py`.
    consent_data_processing_at: Optional[datetime] = None
    consent_policy_version: Optional[str] = None
    consent_withdrawn_at: Optional[datetime] = None
    onboarding_step: str = "identity"
    onboarding_completed: bool = False
    onboarding_completed_at: Optional[datetime] = None
    onboarding_prompt_seen: bool = False
    onboarding_first_seen_at: Optional[datetime] = None
    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    interest_graph: list[str] = Field(default_factory=list)
    achievements: Optional[str] = None
    education: Optional[str] = None
    certificates: Optional[str] = None
    projects: Optional[str] = None
    responsibilities: Optional[str] = None
    # Data minimization, 2026-08-05. Removed: gender, pronouns, date_of_birth,
    # current/permanent_address_line1, _landmark and _pincode. Nothing read any of
    # them — they were collected, stored and never used, which is breach liability
    # with no product return. A pincode plus a college name plus a date of birth
    # de-anonymizes a student outright.
    #
    # `*_region` stays because it is a real ranking input: see
    # `services/personalization/feature_builder.py::_profile_location_tokens`.
    #
    # Legacy documents may still carry the removed keys; Pydantic ignores unknown
    # fields on load, so they are invisible to the app but still resident in Mongo
    # until `scripts/purge_minimized_profile_fields.py` is run against a database.
    current_address_region: Optional[str] = None
    permanent_address_region: Optional[str] = None
    hobbies: list[str] = Field(default_factory=list)
    social_links: dict[str, str] = Field(default_factory=dict)
    resume_url: Optional[str] = None
    resume_filename: Optional[str] = None
    resume_content_type: Optional[str] = None
    resume_storage_key: Optional[str] = None
    resume_uploaded_at: Optional[datetime] = None
    cold_start_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    cold_start_strategy: Optional[str] = None
    preference_embedding: list[float] = Field(default_factory=list)
    preference_embedding_model_version: Optional[str] = None
    preference_embedding_updated_at: Optional[datetime] = None
    persona_cluster_id: Optional[int] = Field(default=None, ge=0)
    taste_calibration_count: int = Field(default=0, ge=0)
    incoscore: float = 0.0

    @field_validator(
        "goals",
        "career_intent",
        "domains_of_interest",
        "work_preferences",
        "opportunity_types",
        "interest_graph",
        "hobbies",
        mode="before",
    )
    @classmethod
    def normalize_optional_string_list(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part and part.strip()]
        return []

    @field_validator("social_links", mode="before")
    @classmethod
    def normalize_optional_social_links(cls, value):
        if value is None:
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items() if str(key).strip() and str(item).strip()}
        return {}

    class Settings:
        name = "profiles"
        indexes = [
            "user_id",
            "preferred_work_mode",
            "graduation_year",
            "persona_cluster_id",
            "preference_embedding_model_version",
            IndexModel([("account_type", 1), ("persona_cluster_id", 1)]),
            IndexModel([("cold_start_strategy", 1), ("cold_start_quality_score", -1)]),
        ]
