from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field, field_validator

class Profile(Document):
    user_id: PydanticObjectId = Field(unique=True)
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
    preferred_roles: Optional[str] = None
    preferred_locations: Optional[str] = None
    pan_india: bool = False
    prefer_wfh: bool = False
    consent_data_processing: bool = False
    consent_updates: bool = False
    onboarding_step: str = "identity"
    onboarding_completed: bool = False
    onboarding_completed_at: Optional[datetime] = None
    onboarding_prompt_seen: bool = False
    onboarding_first_seen_at: Optional[datetime] = None
    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    achievements: Optional[str] = None
    education: Optional[str] = None
    certificates: Optional[str] = None
    projects: Optional[str] = None
    responsibilities: Optional[str] = None
    gender: Optional[str] = None
    pronouns: Optional[str] = None
    date_of_birth: Optional[str] = None
    current_address_line1: Optional[str] = None
    current_address_landmark: Optional[str] = None
    current_address_region: Optional[str] = None
    current_address_pincode: Optional[str] = None
    permanent_address_line1: Optional[str] = None
    permanent_address_landmark: Optional[str] = None
    permanent_address_region: Optional[str] = None
    permanent_address_pincode: Optional[str] = None
    hobbies: list[str] = Field(default_factory=list)
    social_links: dict[str, str] = Field(default_factory=dict)
    resume_url: Optional[str] = None
    resume_filename: Optional[str] = None
    resume_content_type: Optional[str] = None
    resume_storage_key: Optional[str] = None
    resume_uploaded_at: Optional[datetime] = None
    incoscore: float = 0.0

    @field_validator("goals", "hobbies", mode="before")
    @classmethod
    def normalize_optional_string_list(cls, value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
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
        indexes = ["user_id"]
