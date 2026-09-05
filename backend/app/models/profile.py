from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import IndexModel


def _dedupe_skills(value) -> list[str]:
    """Trim, drop blanks, and de-duplicate case-insensitively, preserving order."""
    seen: list[str] = []
    for item in value or []:
        text = str(item).strip()
        if text and text.lower() not in {s.lower() for s in seen}:
            seen.append(text)
    return seen


class EducationEntry(BaseModel):
    """One school or university a candidate attended.

    A list because students genuinely have more than one - school then college -
    and the flat college_name/course/passout_year fields could only ever hold the
    most recent. Those fields stay: personalization and the ranker read them
    (see services/personalization/feature_builder.py), so they are kept in sync
    with the primary entry rather than replaced.

    Months are 1-12 and optional throughout: "expected 2027" with no month is a
    normal thing for a student to know about their own degree.
    """

    school: str = ""
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    start_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    end_month: Optional[int] = Field(default=None, ge=1, le=12)
    end_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    grade: Optional[str] = None
    activities: Optional[str] = None
    description: Optional[str] = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("school", "degree", "field_of_study", "grade", "activities", "description")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value):
        seen: list[str] = []
        for item in value or []:
            text = str(item).strip()
            if text and text.lower() not in {s.lower() for s in seen}:
                seen.append(text)
        return seen

class ExperienceEntry(BaseModel):
    """One role a candidate held.

    Same reasoning as EducationEntry: current_job_role / total_work_experience /
    experience_summary could only describe the newest role, and a student's
    history is usually several short internships. Those fields stay and are kept
    in sync with the current (or most recent) entry, because personalization
    reads them.

    is_current and end_* are mutually exclusive - "I currently work here" is the
    checkbox, and leaving a stale end date behind it would render as a role that
    both ended and is ongoing.
    """

    title: str = ""
    organization: str = ""
    location: Optional[str] = None
    location_type: Optional[str] = None      # on_site | hybrid | remote
    employment_type: Optional[str] = None    # full_time | part_time | internship | ...
    is_current: bool = False
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    start_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    end_month: Optional[int] = Field(default=None, ge=1, le=12)
    end_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    highlights: Optional[str] = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("title", "organization", "location", "location_type",
                     "employment_type", "highlights")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value):
        seen: list[str] = []
        for item in value or []:
            text = str(item).strip()
            if text and text.lower() not in {s.lower() for s in seen}:
                seen.append(text)
        return seen

    @model_validator(mode="after")
    def _current_role_has_no_end_date(self):
        if self.is_current:
            self.end_month = None
            self.end_year = None
        return self


class ProjectEntry(BaseModel):
    """One project a candidate built.

    Replaces a free-text `projects` blob. Structure matters here because the
    ranker and the resume builder both want a title and a date range, and neither
    can get that out of a paragraph reliably.
    """

    name: str = ""
    description: Optional[str] = None
    url: Optional[str] = None
    is_current: bool = False
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    start_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    end_month: Optional[int] = Field(default=None, ge=1, le=12)
    end_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    skills: list[str] = Field(default_factory=list)

    @field_validator("name", "description", "url")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value):
        return _dedupe_skills(value)

    @model_validator(mode="after")
    def _ongoing_project_has_no_end_date(self):
        if self.is_current:
            self.end_month = None
            self.end_year = None
        return self


class CertificationEntry(BaseModel):
    """One licence or certification, with the credential that proves it."""

    name: str = ""
    issuing_organization: Optional[str] = None
    issue_month: Optional[int] = Field(default=None, ge=1, le=12)
    issue_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    expiry_month: Optional[int] = Field(default=None, ge=1, le=12)
    expiry_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    credential_id: Optional[str] = None
    credential_url: Optional[str] = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("name", "issuing_organization", "credential_id", "credential_url")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value):
        return _dedupe_skills(value)


class HonorEntry(BaseModel):
    """One honour or award."""

    title: str = ""
    issuer: Optional[str] = None
    issue_month: Optional[int] = Field(default=None, ge=1, le=12)
    issue_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    description: Optional[str] = None

    @field_validator("title", "issuer", "description")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None


class VolunteerEntry(BaseModel):
    """One volunteering role.

    Kept separate from ExperienceEntry: unpaid community work is not a job, and
    conflating them would put "Educator, Dhagagia Social Welfare Society" into a
    work history the ranker treats as professional experience.
    """

    organization: str = ""
    role: str = ""
    cause: Optional[str] = None
    is_current: bool = False
    start_month: Optional[int] = Field(default=None, ge=1, le=12)
    start_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    end_month: Optional[int] = Field(default=None, ge=1, le=12)
    end_year: Optional[int] = Field(default=None, ge=1950, le=2100)
    description: Optional[str] = None

    @field_validator("organization", "role", "cause", "description")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

    @model_validator(mode="after")
    def _current_role_has_no_end_date(self):
        if self.is_current:
            self.end_month = None
            self.end_year = None
        return self


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

    # --- Academician -------------------------------------------------------
    # A faculty profile is described by where they teach and what they teach,
    # not by a skills list and a job-role preference. Asking an academician for
    # their "preferred work mode" is asking a question from somebody else's form.
    department: Optional[str] = None
    designation: Optional[str] = None
    specialisation: Optional[str] = None
    teaching_experience_years: Optional[int] = Field(default=None, ge=0, le=70)
    #: Vidwan is INFLIBNET's national expert database; most Indian academics
    #: already have an id there, and it is the closest thing to a portable
    #: academic identity in this system.
    vidwan_id: Optional[str] = None

    # --- Institution -------------------------------------------------------
    institution_type: Optional[str] = None
    #: The Ministry of Education's own identifier, issued when an institution
    #: registers on the AISHE portal. Every recognised higher education
    #: institution in India has one, which makes it the only field here that can
    #: later be checked against an authoritative list rather than trusted.
    aishe_code: Optional[str] = None
    institution_city: Optional[str] = None
    institution_state: Optional[str] = None
    institution_website: Optional[str] = None
    #: The human filling the form is not the account holder here - the
    #: institution is - so their role has to be recorded separately.
    contact_designation: Optional[str] = None
    student_strength: Optional[int] = Field(default=None, ge=0, le=1_000_000)
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
    # The structured replacement for the free-text `education` field above, which
    # is kept so existing profiles do not lose what they already wrote.
    education_entries: list[EducationEntry] = Field(default_factory=list)
    experience_entries: list[ExperienceEntry] = Field(default_factory=list)
    project_entries: list[ProjectEntry] = Field(default_factory=list)
    certification_entries: list[CertificationEntry] = Field(default_factory=list)
    honor_entries: list[HonorEntry] = Field(default_factory=list)
    volunteer_entries: list[VolunteerEntry] = Field(default_factory=list)
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
