from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field

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
    passout_year: Optional[int] = None
    class_grade: Optional[int] = None
    current_job_role: Optional[str] = None
    total_work_experience: Optional[str] = None
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
    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    achievements: Optional[str] = None
    education: Optional[str] = None
    resume_url: Optional[str] = None
    incoscore: float = 0.0

    class Settings:
        name = "profiles"
        indexes = ["user_id"]
