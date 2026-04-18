from datetime import datetime, timezone
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_active_user
from app.models.profile import Profile
from app.models.user import User
from app.schemas.user import UserResponse
from app.services.intelligence import calculate_incoscore

router = APIRouter()

VALID_ACCOUNT_TYPES = {"candidate", "employer"}
VALID_USER_TYPES = {"school_student", "college_student", "fresher", "professional"}


class ProfileUpdate(BaseModel):
    account_type: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    country_code: Optional[str] = None
    user_type: Optional[str] = None
    domain: Optional[str] = None
    course: Optional[str] = None
    passout_year: Optional[int] = None
    class_grade: Optional[int] = None
    current_job_role: Optional[str] = None
    total_work_experience: Optional[str] = None
    college_name: Optional[str] = None
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
    resume_url: Optional[str] = None

    @field_validator("account_type", mode="before")
    @classmethod
    def normalize_account_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if candidate not in VALID_ACCOUNT_TYPES:
            raise ValueError("account_type must be candidate or employer")
        return candidate

    @field_validator("user_type", mode="before")
    @classmethod
    def normalize_user_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if candidate not in VALID_USER_TYPES:
            raise ValueError("user_type must be school_student, college_student, fresher, or professional")
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
    passout_year: Optional[int] = None
    class_grade: Optional[int] = None
    current_job_role: Optional[str] = None
    total_work_experience: Optional[str] = None
    college_name: Optional[str] = None
    goals: list[str] = Field(default_factory=list)
    preferred_roles: Optional[str] = None
    preferred_locations: Optional[str] = None
    pan_india: bool = False
    prefer_wfh: bool = False
    consent_data_processing: bool = False
    consent_updates: bool = False
    onboarding_step: str = "identity"
    onboarding_completed: bool = False

    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    achievements: Optional[str] = None
    education: Optional[str] = None
    resume_url: Optional[str] = None
    incoscore: float

    class Config:
        from_attributes = True


class OnboardingStatusResponse(BaseModel):
    completed: bool
    progress_percent: int
    missing_fields: list[str]
    recommended_next_step: str


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


def _sync_profile_identity(profile: Profile, user: User) -> None:
    if not (profile.account_type or "").strip():
        profile.account_type = (user.account_type or "candidate").strip().lower()

    if not (profile.first_name or "").strip() and user.full_name:
        first_name, last_name = _split_full_name(user.full_name)
        profile.first_name = first_name
        profile.last_name = last_name


def _apply_profile_patch(*, profile: Profile, user: User, payload: ProfileUpdate) -> None:
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)

    # Keep account type mirrored between User and Profile when explicitly changed.
    if payload.account_type and payload.account_type in VALID_ACCOUNT_TYPES and user.account_type != payload.account_type:
        user.account_type = payload.account_type

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
    return current_user


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
    Upload resume, parse skills via AI, and update profile InCoScore.
    """
    filename = file.filename or ""
    if not filename.endswith(".txt"):
        # For simplicity in this implementation, we only accept txt.
        raise HTTPException(status_code=400, detail="Only .txt files are supported for this MVP")

    content = await file.read()
    text = content.decode("utf-8")

    from app.services.ai_engine import ai_system

    parsed_data = ai_system.parse_resume(text)

    profile = await _get_or_create_profile_for_user(current_user)
    parsed_skills = parsed_data.get("skills", [])
    profile.skills = _merge_csv_values(profile.skills, parsed_skills)
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
