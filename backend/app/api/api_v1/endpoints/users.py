from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_active_user
from app.core.email_policy import is_corporate_email
from app.models.profile import Profile
from app.models.user import User
from app.schemas.user import UserResponse
from app.services.intelligence import calculate_incoscore

router = APIRouter()

VALID_ACCOUNT_TYPES = {"candidate", "employer"}
VALID_USER_TYPES = {"school_student", "college_student", "fresher", "professional"}
VALID_HIRING_FOR = {"myself", "others"}
RESUME_REQUIRED_USER_TYPES = {"college_student", "fresher", "professional"}
ALLOWED_RESUME_EXTENSIONS = {".txt", ".pdf", ".docx", ".doc"}
RESUME_STORAGE_RELATIVE_DIR = Path("storage") / "resumes"
RESUME_MAX_FILE_SIZE_MB = 8

PROFILE_SIGNAL_METADATA: dict[str, tuple[str, str]] = {
    "first_name": ("First Name", "Add your first name."),
    "last_name": ("Last Name", "Add your last name."),
    "mobile": ("Mobile Number", "Add a valid mobile number."),
    "consent_data_processing": ("Privacy Consent", "Accept privacy and data processing policy."),
    "user_type": ("User Type", "Select your current user type."),
    "class_grade": ("Class/Grade", "Select your current class/grade."),
    "domain": ("Domain", "Select your academic/professional domain."),
    "course": ("Course", "Add your course or degree."),
    "course_specialization": ("Course Specialization", "Add your major or specialization."),
    "passout_year": ("Passout Year", "Choose your graduation/passout year."),
    "college_name": ("College Name", "Add your institute/college name."),
    "current_job_role": ("Current Job Role", "Add your current role."),
    "total_work_experience": ("Work Experience", "Add your total work experience."),
    "experience_summary": ("Experience Summary", "Describe your work experience."),
    "bio": ("Bio", "Write a short profile bio."),
    "skills": ("Skills", "Add your core skills."),
    "interests": ("Interests", "Add your interests."),
    "education": ("Education", "Add education details."),
    "certificates": ("Certificates", "Add relevant certifications."),
    "projects": ("Projects", "Add your key projects."),
    "responsibilities": ("Responsibilities", "Add initiatives or leadership responsibilities."),
    "gender": ("Gender", "Select your gender identity."),
    "pronouns": ("Pronouns", "Add your pronouns."),
    "date_of_birth": ("Date of Birth", "Add your date of birth."),
    "current_address_line1": ("Current Address", "Add your current address."),
    "permanent_address_line1": ("Permanent Address", "Add your permanent address."),
    "hobbies": ("Hobbies", "Add hobbies or personal interests."),
    "social_links": ("Social Links", "Add at least one professional or social link."),
    "resume": ("Resume", "Upload resume/CV."),
    "company_name": ("Company Name", "Add your company name."),
    "hiring_for": ("Hiring For", "Select whether you hire for yourself or others."),
    "company_website": ("Company Website", "Add company website URL."),
    "company_description": ("Company Description", "Add a short company description."),
}


class ProfileUpdate(BaseModel):
    account_type: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    country_code: Optional[str] = None
    user_type: Optional[str] = None
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
    hiring_for: Optional[str] = None
    goals: Optional[list[str]] = None
    preferred_roles: Optional[str] = None
    preferred_locations: Optional[str] = None
    pan_india: Optional[bool] = None
    prefer_wfh: Optional[bool] = None
    consent_data_processing: Optional[bool] = None
    consent_updates: Optional[bool] = None

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
    hobbies: Optional[list[str] | str] = None
    social_links: Optional[dict[str, str]] = None
    resume_url: Optional[str] = None
    resume_filename: Optional[str] = None
    resume_content_type: Optional[str] = None
    resume_uploaded_at: Optional[datetime] = None

    @field_validator("resume_url", "resume_filename", "resume_content_type", mode="before")
    @classmethod
    def normalize_optional_resume_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("resume_uploaded_at", mode="before")
    @classmethod
    def normalize_resume_uploaded_at(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("account_type", mode="before")
    @classmethod
    def normalize_account_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if not candidate:
            return None
        if candidate not in VALID_ACCOUNT_TYPES:
            raise ValueError("account_type must be candidate or employer")
        return candidate

    @field_validator("user_type", mode="before")
    @classmethod
    def normalize_user_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if not candidate:
            return None
        if candidate in {"educator", "education_professional", "teacher"}:
            candidate = "professional"
        if candidate not in VALID_USER_TYPES:
            raise ValueError("user_type must be school_student, college_student, fresher, or professional")
        return candidate

    @field_validator("hiring_for", mode="before")
    @classmethod
    def normalize_hiring_for(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if not candidate:
            return None
        if candidate not in VALID_HIRING_FOR:
            raise ValueError("hiring_for must be myself or others")
        return candidate

    @field_validator("goals", mode="before")
    @classmethod
    def normalize_goals(cls, value: Optional[list[str] | str]) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            parts = [chunk.strip() for chunk in value.split(",")]
        else:
            parts = [str(chunk).strip() for chunk in value]
        clean: list[str] = []
        seen: set[str] = set()
        for part in parts:
            key = part.lower()
            if not part or key in seen:
                continue
            seen.add(key)
            clean.append(part)
        return clean[:8]

    @field_validator("hobbies", mode="before")
    @classmethod
    def normalize_hobbies(cls, value: Optional[list[str] | str]) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            parts = [chunk.strip() for chunk in value.split(",")]
        else:
            parts = [str(chunk).strip() for chunk in value]
        clean: list[str] = []
        seen: set[str] = set()
        for part in parts:
            key = part.lower()
            if not part or key in seen:
                continue
            seen.add(key)
            clean.append(part)
        return clean[:12]

    @field_validator("social_links", mode="before")
    @classmethod
    def normalize_social_links(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("social_links must be an object")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            clean_key = str(key).strip().lower()
            clean_value = str(item).strip()
            if not clean_key or not clean_value:
                continue
            normalized[clean_key] = clean_value
        return normalized or None


class ProfileResponse(BaseModel):
    user_id: PydanticObjectId
    account_type: str = "candidate"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    country_code: str = "+91"
    user_type: Optional[str] = None
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
    hiring_for: Optional[str] = None
    goals: list[str] = Field(default_factory=list)
    preferred_roles: Optional[str] = None
    preferred_locations: Optional[str] = None
    pan_india: bool = False
    prefer_wfh: bool = False
    consent_data_processing: bool = False
    consent_updates: bool = False
    onboarding_step: str = "identity"
    onboarding_completed: bool = False
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
    resume_uploaded_at: Optional[datetime] = None
    incoscore: float

    class Config:
        from_attributes = True


class OnboardingStatusResponse(BaseModel):
    completed: bool
    progress_percent: int
    missing_fields: list[str]
    recommended_next_step: str


class OnboardingPromptSeenResponse(BaseModel):
    onboarding_prompt_seen: bool
    onboarding_first_seen_at: Optional[datetime] = None


class RankingSummaryResponse(BaseModel):
    account_scope: str
    incoscore: float
    rank: int
    total_users: int
    top_percent: float
    percentile: float
    updated_at: datetime


class ProfileSignalDetail(BaseModel):
    key: str
    label: str
    description: str


class ProfileStrengthResponse(BaseModel):
    account_scope: str
    strength_percent: int
    completed_signals: int
    total_signals: int
    missing_signals: list[str]
    missing_signal_details: list[ProfileSignalDetail] = Field(default_factory=list)
    recommendation: str
    updated_at: datetime


class LeaderboardEntry(BaseModel):
    user_id: str
    full_name: Optional[str] = None
    email: str
    incoscore: float


def _merge_csv_values(existing: Optional[str], incoming_values: list[str]) -> str:
    current = [item.strip() for item in (existing or "").split(",") if item.strip()]
    merged = current + incoming_values
    deduped: list[str] = []
    seen: set[str] = set()
    for value in merged:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return ", ".join(deduped)


def _split_full_name(full_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    text = (full_name or "").strip()
    if not text:
        return None, None
    parts = text.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _required_onboarding_checks(profile: Profile) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = [
        ("first_name", bool((profile.first_name or "").strip())),
        ("mobile", bool((profile.mobile or "").strip())),
        ("account_type", bool((profile.account_type or "").strip() in VALID_ACCOUNT_TYPES)),
        ("consent_data_processing", bool(profile.consent_data_processing)),
    ]

    if profile.account_type == "candidate":
        user_type = (profile.user_type or "").strip().lower()
        checks.append(("user_type", user_type in VALID_USER_TYPES))
        if user_type == "school_student":
            checks.append(("class_grade", profile.class_grade is not None))
        elif user_type in {"college_student", "fresher"}:
            checks.append(("domain", bool((profile.domain or "").strip())))
            checks.append(("course", bool((profile.course or "").strip())))
            checks.append(("passout_year", profile.passout_year is not None))
            checks.append(("college_name", bool((profile.college_name or "").strip())))
        elif user_type == "professional":
            checks.append(("current_job_role", bool((profile.current_job_role or "").strip())))
            checks.append(("total_work_experience", bool((profile.total_work_experience or "").strip())))
        if user_type in RESUME_REQUIRED_USER_TYPES:
            checks.append(("resume", bool((profile.resume_url or "").strip())))
    elif profile.account_type == "employer":
        checks.append(("company_name", bool((profile.company_name or "").strip())))
        checks.append(("current_job_role", bool((profile.current_job_role or "").strip())))
        checks.append(("hiring_for", str(profile.hiring_for or "").strip().lower() in VALID_HIRING_FOR))

    return checks


def _compute_onboarding_status(profile: Profile) -> tuple[bool, int, list[str], str]:
    checks = _required_onboarding_checks(profile)
    total = max(1, len(checks))
    completed_count = sum(1 for _field, ok in checks if ok)
    missing = [field for field, ok in checks if not ok]
    progress_percent = int(round((completed_count / total) * 100.0))
    is_complete = len(missing) == 0
    next_step = "profile_complete" if is_complete else missing[0]
    return is_complete, progress_percent, missing, next_step


def _normalize_account_scope(account_type: Optional[str]) -> str:
    return "employer" if str(account_type or "").strip().lower() == "employer" else "candidate"


def _resume_storage_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    root = repo_root / RESUME_STORAGE_RELATIVE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_resume_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower().strip()
    if suffix not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported resume format. Allowed: .txt, .pdf, .docx, .doc",
        )
    return suffix


def _extract_resume_text(*, extension: str, content: bytes) -> str:
    if extension == ".txt":
        return content.decode("utf-8", errors="ignore")

    if extension == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return ""
        try:
            from io import BytesIO

            reader = PdfReader(BytesIO(content))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

    if extension == ".docx":
        try:
            from docx import Document  # type: ignore
        except Exception:
            return ""
        try:
            from io import BytesIO

            doc = Document(BytesIO(content))
            return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text)
        except Exception:
            return ""

    # Legacy .doc is retained for storage, but parsing is not guaranteed.
    return ""


def _profile_signal_detail(key: str) -> ProfileSignalDetail:
    label, description = PROFILE_SIGNAL_METADATA.get(
        key,
        (key.replace("_", " ").title(), "Complete this field to improve profile completeness."),
    )
    return ProfileSignalDetail(key=key, label=label, description=description)


def _missing_signal_details(keys: list[str]) -> list[ProfileSignalDetail]:
    return [_profile_signal_detail(key) for key in keys]


def _clean_text_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_passout_year(value: Any) -> Optional[int]:
    try:
        year = int(value)
    except Exception:
        return None
    if 1990 <= year <= 2100:
        return year
    return None


def _format_experience(years_value: Any, fallback_text: Any) -> Optional[str]:
    fallback = _clean_text_value(fallback_text)
    if fallback:
        return fallback
    try:
        years = float(years_value)
    except Exception:
        return None
    if years < 0:
        return None
    return f"{years:g} years"


def _merge_pipe_values(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
    current = [chunk.strip() for chunk in (existing or "").split("|") if chunk.strip()]
    extra = [chunk.strip() for chunk in (incoming or "").split("|") if chunk.strip()]
    merged = current + extra
    seen: set[str] = set()
    output: list[str] = []
    for item in merged:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    joined = " | ".join(output)
    return joined or None


def _apply_parsed_resume_signals(*, profile: Profile, parsed_data: dict[str, Any]) -> None:
    parsed_skills_raw = parsed_data.get("skills", [])
    if isinstance(parsed_skills_raw, list):
        parsed_skills = [str(item).strip() for item in parsed_skills_raw if str(item).strip()]
    else:
        parsed_skills = []
    if parsed_skills:
        profile.skills = _merge_csv_values(profile.skills, parsed_skills)

    education_text = _clean_text_value(parsed_data.get("education"))
    if education_text:
        profile.education = _merge_pipe_values(profile.education, education_text)

    inferred_domain = _clean_text_value(parsed_data.get("inferred_domain"))
    if inferred_domain and not _clean_text_value(profile.domain):
        profile.domain = inferred_domain

    inferred_course = _clean_text_value(parsed_data.get("course"))
    if inferred_course and not _clean_text_value(profile.course):
        profile.course = inferred_course

    inferred_college = _clean_text_value(parsed_data.get("college_name"))
    if inferred_college and not _clean_text_value(profile.college_name):
        profile.college_name = inferred_college

    inferred_year = _safe_passout_year(parsed_data.get("passout_year"))
    if inferred_year is not None and profile.passout_year is None:
        profile.passout_year = inferred_year

    inferred_role = _clean_text_value(parsed_data.get("current_job_role"))
    if inferred_role and not _clean_text_value(profile.current_job_role):
        profile.current_job_role = inferred_role

    inferred_experience = _format_experience(
        parsed_data.get("years_of_experience"),
        parsed_data.get("total_work_experience"),
    )
    if inferred_experience and not _clean_text_value(profile.total_work_experience):
        profile.total_work_experience = inferred_experience

    user_type_hint = _clean_text_value(parsed_data.get("user_type_hint"))
    if user_type_hint:
        normalized = user_type_hint.lower().strip()
        if normalized in {"educator", "education_professional", "teacher"}:
            normalized = "professional"
        if normalized in VALID_USER_TYPES and not _clean_text_value(profile.user_type):
            profile.user_type = normalized

    organizations_raw = parsed_data.get("organizations", [])
    organizations = [str(item).strip() for item in organizations_raw if str(item).strip()] if isinstance(organizations_raw, list) else []
    if organizations and str(profile.account_type or "").strip().lower() == "employer" and not _clean_text_value(profile.company_name):
        profile.company_name = organizations[0]


def _compute_rank_stats(*, rank: int, total_users: int) -> tuple[float, float]:
    safe_total = max(1, int(total_users))
    safe_rank = max(1, min(int(rank), safe_total))
    top_percent = round((safe_rank / safe_total) * 100.0, 2)
    percentile = round(((safe_total - safe_rank) / safe_total) * 100.0, 2)
    return top_percent, percentile


async def _build_ranking_summary(profile: Profile) -> RankingSummaryResponse:
    scope = _normalize_account_scope(profile.account_type)
    scope_filters = [Profile.account_type == scope]

    total_users = int(await Profile.find(*scope_filters).count())
    if total_users <= 0:
        total_users = 1

    higher_count = int(await Profile.find(*scope_filters, Profile.incoscore > float(profile.incoscore)).count())
    rank = max(1, higher_count + 1)
    top_percent, percentile = _compute_rank_stats(rank=rank, total_users=total_users)

    return RankingSummaryResponse(
        account_scope=scope,
        incoscore=float(profile.incoscore),
        rank=rank,
        total_users=total_users,
        top_percent=top_percent,
        percentile=percentile,
        updated_at=datetime.now(timezone.utc),
    )


def _profile_strength_checks(profile: Profile) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = [
        ("first_name", bool((profile.first_name or "").strip())),
        ("last_name", bool((profile.last_name or "").strip())),
        ("mobile", bool((profile.mobile or "").strip())),
        ("consent_data_processing", bool(profile.consent_data_processing)),
    ]

    scope = _normalize_account_scope(profile.account_type)
    if scope == "candidate":
        user_type = str(profile.user_type or "").strip().lower()
        checks.append(("user_type", user_type in VALID_USER_TYPES))

        if user_type == "school_student":
            checks.append(("class_grade", profile.class_grade is not None))
        elif user_type in {"college_student", "fresher"}:
            checks.extend(
                [
                    ("domain", bool((profile.domain or "").strip())),
                    ("course", bool((profile.course or "").strip())),
                    ("course_specialization", bool((profile.course_specialization or "").strip())),
                    ("passout_year", profile.passout_year is not None),
                    ("college_name", bool((profile.college_name or "").strip())),
                ]
            )
        elif user_type == "professional":
            checks.extend(
                [
                    ("current_job_role", bool((profile.current_job_role or "").strip())),
                    ("total_work_experience", bool((profile.total_work_experience or "").strip())),
                    ("experience_summary", bool((profile.experience_summary or "").strip())),
                ]
            )

        checks.extend(
            [
                ("bio", bool((profile.bio or "").strip())),
                ("skills", bool((profile.skills or "").strip())),
                ("interests", bool((profile.interests or "").strip())),
                ("education", bool((profile.education or "").strip())),
                ("projects", bool((profile.projects or "").strip())),
                ("date_of_birth", bool((profile.date_of_birth or "").strip())),
                ("current_address_line1", bool((profile.current_address_line1 or "").strip())),
                ("hobbies", len(profile.hobbies or []) > 0),
                ("social_links", len(profile.social_links or {}) > 0),
                ("resume", bool((profile.resume_url or "").strip())),
            ]
        )
    else:
        checks.extend(
            [
                ("company_name", bool((profile.company_name or "").strip())),
                ("current_job_role", bool((profile.current_job_role or "").strip())),
                ("hiring_for", str(profile.hiring_for or "").strip().lower() in VALID_HIRING_FOR),
                ("company_website", bool((profile.company_website or "").strip())),
                ("company_description", bool((profile.company_description or "").strip())),
            ]
        )

    return checks


def _strength_recommendation(missing_signals: list[str]) -> str:
    if len(missing_signals) == 0:
        return "Profile is complete and ranked-ready."
    if "resume" in missing_signals:
        return "Upload resume and skills to unlock higher-quality recommendations."
    if "skills" in missing_signals or "bio" in missing_signals:
        return "Add bio and skills to improve matching relevance."
    first = missing_signals[0].replace("_", " ")
    return f"Complete {first} to improve profile strength."


def _build_profile_strength_summary(profile: Profile) -> ProfileStrengthResponse:
    checks = _profile_strength_checks(profile)
    total = max(1, len(checks))
    completed = sum(1 for _name, done in checks if done)
    missing = [name for name, done in checks if not done]
    strength_percent = int(round((completed / total) * 100.0))
    return ProfileStrengthResponse(
        account_scope=_normalize_account_scope(profile.account_type),
        strength_percent=strength_percent,
        completed_signals=completed,
        total_signals=total,
        missing_signals=missing,
        missing_signal_details=_missing_signal_details(missing),
        recommendation=_strength_recommendation(missing),
        updated_at=datetime.now(timezone.utc),
    )


def _sync_profile_identity(profile: Profile, user: User) -> None:
    if not (profile.account_type or "").strip():
        profile.account_type = (user.account_type or "candidate").strip().lower()

    if not (profile.first_name or "").strip() and user.full_name:
        first_name, last_name = _split_full_name(user.full_name)
        profile.first_name = first_name
        profile.last_name = last_name

    if str(profile.account_type or "").strip().lower() == "employer":
        if not (profile.company_name or "").strip():
            candidate = (profile.college_name or "").strip() or (user.full_name or "").strip()
            profile.company_name = candidate or None


def _apply_profile_patch(*, profile: Profile, user: User, payload: ProfileUpdate) -> None:
    updates = payload.model_dump(exclude_unset=True)
    for immutable_resume_field in ("resume_url", "resume_filename", "resume_content_type", "resume_uploaded_at"):
        updates.pop(immutable_resume_field, None)

    target_account_type = payload.account_type or profile.account_type or user.account_type or "candidate"
    if str(target_account_type).strip().lower() == "employer" and not is_corporate_email(user.email):
        raise HTTPException(
            status_code=400,
            detail="Employer account setup requires a corporate email (personal providers are not allowed).",
        )

    for field, value in updates.items():
        setattr(profile, field, value)

    # Keep account type mirrored between User and Profile when explicitly changed.
    if payload.account_type and payload.account_type in VALID_ACCOUNT_TYPES and user.account_type != payload.account_type:
        user.account_type = payload.account_type

    if str(profile.account_type or "").strip().lower() == "employer":
        if not (profile.company_name or "").strip() and (profile.college_name or "").strip():
            profile.company_name = (profile.college_name or "").strip()
        if not (profile.college_name or "").strip() and (profile.company_name or "").strip():
            profile.college_name = (profile.company_name or "").strip()

    _sync_profile_identity(profile, user)
    is_complete, _progress, _missing, next_step = _compute_onboarding_status(profile)
    profile.onboarding_completed = is_complete
    profile.onboarding_step = "complete" if is_complete else next_step
    profile.onboarding_completed_at = datetime.now(timezone.utc) if is_complete else None
    profile.incoscore = calculate_incoscore(profile)


async def _get_or_create_profile_for_user(user: User) -> Profile:
    profile = await Profile.find_one(Profile.user_id == user.id)
    if profile:
        _sync_profile_identity(profile, user)
        is_complete, _progress, _missing, next_step = _compute_onboarding_status(profile)
        profile.onboarding_completed = is_complete
        profile.onboarding_step = "complete" if is_complete else next_step
        profile.incoscore = calculate_incoscore(profile)
        await profile.save()
        return profile

    first_name, last_name = _split_full_name(user.full_name)
    profile = Profile(
        user_id=user.id,
        account_type=(user.account_type or "candidate").strip().lower(),
        first_name=first_name,
        last_name=last_name,
    )
    profile.incoscore = calculate_incoscore(profile)
    is_complete, _progress, _missing, next_step = _compute_onboarding_status(profile)
    profile.onboarding_completed = is_complete
    profile.onboarding_step = "complete" if is_complete else next_step
    profile.onboarding_completed_at = datetime.now(timezone.utc) if is_complete else None
    await profile.insert()
    return profile


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Get current user.
    """
    return UserResponse.model_validate(current_user)


@router.get("/me/profile", response_model=ProfileResponse)
async def read_profile_me(
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Get current user profile.
    """
    profile = await _get_or_create_profile_for_user(current_user)
    return profile


@router.get("/me/onboarding-status", response_model=OnboardingStatusResponse)
async def read_onboarding_status(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    profile = await _get_or_create_profile_for_user(current_user)
    completed, progress_percent, missing_fields, next_step = _compute_onboarding_status(profile)
    return OnboardingStatusResponse(
        completed=completed,
        progress_percent=progress_percent,
        missing_fields=missing_fields,
        recommended_next_step=next_step,
    )


@router.post("/me/onboarding/mark-seen", response_model=OnboardingPromptSeenResponse)
async def mark_onboarding_seen(
    current_user: User = Depends(get_current_active_user),
) -> OnboardingPromptSeenResponse:
    """
    Marks that onboarding has been shown once for this user.
    Used to prevent forcing onboarding on every subsequent login.
    """
    profile = await _get_or_create_profile_for_user(current_user)
    if not bool(profile.onboarding_prompt_seen):
        profile.onboarding_prompt_seen = True
        if profile.onboarding_first_seen_at is None:
            profile.onboarding_first_seen_at = datetime.now(timezone.utc)
        await profile.save()
    return OnboardingPromptSeenResponse(
        onboarding_prompt_seen=bool(profile.onboarding_prompt_seen),
        onboarding_first_seen_at=profile.onboarding_first_seen_at,
    )


@router.get("/me/ranking-summary", response_model=RankingSummaryResponse)
async def read_ranking_summary(
    current_user: User = Depends(get_current_active_user),
) -> RankingSummaryResponse:
    profile = await _get_or_create_profile_for_user(current_user)
    return await _build_ranking_summary(profile)


@router.get("/me/profile-strength", response_model=ProfileStrengthResponse)
async def read_profile_strength(
    current_user: User = Depends(get_current_active_user),
) -> ProfileStrengthResponse:
    profile = await _get_or_create_profile_for_user(current_user)
    return _build_profile_strength_summary(profile)


@router.put("/me/profile", response_model=ProfileResponse)
async def update_profile_me(
    profile_in: ProfileUpdate,
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Update current user profile.
    """
    profile = await _get_or_create_profile_for_user(current_user)
    _apply_profile_patch(profile=profile, user=current_user, payload=profile_in)
    await current_user.save()
    await profile.save()
    return profile


@router.put("/me/onboarding", response_model=ProfileResponse)
async def update_onboarding_me(
    profile_in: ProfileUpdate,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Guided onboarding update endpoint for multi-step profile setup.
    """
    profile = await _get_or_create_profile_for_user(current_user)
    _apply_profile_patch(profile=profile, user=current_user, payload=profile_in)
    await current_user.save()
    await profile.save()
    return profile


@router.post("/me/resume", response_model=ProfileResponse)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Upload resume, persist file, parse text when supported, and update profile personalization signals.
    """
    filename = (file.filename or "resume.txt").strip() or "resume.txt"
    extension = _safe_resume_extension(filename)
    content = await file.read()
    size_limit_bytes = int(max(1, RESUME_MAX_FILE_SIZE_MB)) * 1024 * 1024
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    if len(content) > size_limit_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Resume exceeds maximum size ({RESUME_MAX_FILE_SIZE_MB} MB).",
        )

    profile = await _get_or_create_profile_for_user(current_user)
    storage_key = f"{str(current_user.id)}_{uuid4().hex}{extension}"
    storage_path = _resume_storage_dir() / storage_key
    storage_path.write_bytes(content)

    previous_key = (profile.resume_storage_key or "").strip()
    if previous_key:
        previous_path = _resume_storage_dir() / previous_key
        if previous_path.exists():
            previous_path.unlink(missing_ok=True)

    text = _extract_resume_text(extension=extension, content=content).strip()
    if text:
        from app.services.ai_engine import ai_system

        try:
            parsed_data = ai_system.parse_resume(text)
        except Exception:
            parsed_data = {}
        if isinstance(parsed_data, dict) and parsed_data:
            _apply_parsed_resume_signals(profile=profile, parsed_data=parsed_data)

    profile.resume_url = "/api/v1/users/me/resume/download"
    profile.resume_filename = filename
    profile.resume_content_type = (file.content_type or "application/octet-stream").strip() or "application/octet-stream"
    profile.resume_storage_key = storage_key
    profile.resume_uploaded_at = datetime.now(timezone.utc)
    _sync_profile_identity(profile, current_user)
    is_complete, _progress, _missing, next_step = _compute_onboarding_status(profile)
    profile.onboarding_completed = is_complete
    profile.onboarding_step = "complete" if is_complete else next_step
    profile.onboarding_completed_at = datetime.now(timezone.utc) if is_complete else None
    profile.incoscore = calculate_incoscore(profile)

    await profile.save()
    return profile


@router.get("/me/resume/download")
async def download_resume(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    profile = await _get_or_create_profile_for_user(current_user)
    storage_key = (profile.resume_storage_key or "").strip()
    if not storage_key:
        raise HTTPException(status_code=404, detail="No resume uploaded.")

    storage_path = _resume_storage_dir() / storage_key
    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="Stored resume not found.")

    return FileResponse(
        path=storage_path,
        media_type=(profile.resume_content_type or "application/octet-stream"),
        filename=profile.resume_filename or "resume",
    )


@router.delete("/me/resume", response_model=ProfileResponse)
async def delete_resume(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    profile = await _get_or_create_profile_for_user(current_user)
    storage_key = (profile.resume_storage_key or "").strip()
    if storage_key:
        storage_path = _resume_storage_dir() / storage_key
        if storage_path.exists():
            storage_path.unlink(missing_ok=True)

    profile.resume_url = None
    profile.resume_filename = None
    profile.resume_content_type = None
    profile.resume_storage_key = None
    profile.resume_uploaded_at = None
    is_complete, _progress, _missing, next_step = _compute_onboarding_status(profile)
    profile.onboarding_completed = is_complete
    profile.onboarding_step = "complete" if is_complete else next_step
    profile.onboarding_completed_at = datetime.now(timezone.utc) if is_complete else None
    profile.incoscore = calculate_incoscore(profile)
    await profile.save()
    return profile


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(limit: int = 20) -> Any:
    """
    Global InCoScore leaderboard used for ranking and smart shortlisting views.
    """
    safe_limit = max(1, min(limit, 100))
    profiles = await Profile.find_all().sort("-incoscore").limit(safe_limit).to_list()

    leaderboard: list[LeaderboardEntry] = []
    for profile in profiles:
        user = await User.get(profile.user_id)
        if not user:
            continue
        leaderboard.append(
            LeaderboardEntry(
                user_id=str(user.id),
                full_name=user.full_name,
                email=user.email,
                incoscore=profile.incoscore,
            )
        )

    return leaderboard
