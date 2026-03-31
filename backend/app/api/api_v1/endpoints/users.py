from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Any, Optional
from pydantic import BaseModel
from beanie import PydanticObjectId

from app.api.deps import get_current_active_user
from app.models.user import User
from app.models.profile import Profile
from app.schemas.user import UserResponse
from app.services.intelligence import calculate_incoscore

router = APIRouter()

class ProfileUpdate(BaseModel):
    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    achievements: Optional[str] = None
    education: Optional[str] = None
    resume_url: Optional[str] = None

class ProfileResponse(BaseModel):
    user_id: PydanticObjectId
    bio: Optional[str]
    skills: Optional[str]
    interests: Optional[str]
    achievements: Optional[str]
    education: Optional[str]
    resume_url: Optional[str]
    incoscore: float

    class Config:
        from_attributes = True

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
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    if not profile:
        profile = Profile(user_id=current_user.id)
        profile.incoscore = calculate_incoscore(profile)
        await profile.insert()
        
    return profile

@router.put("/me/profile", response_model=ProfileResponse)
async def update_profile_me(
    profile_in: ProfileUpdate,
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Update current user profile.
    """
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    if not profile:
        profile = Profile(user_id=current_user.id)
        await profile.insert()
        
    for field, value in profile_in.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    profile.incoscore = calculate_incoscore(profile)

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
        # In a real system, we'd use PyPDF2 or pdfminer to extract text.
        raise HTTPException(status_code=400, detail="Only .txt files are supported for this MVP")
        
    content = await file.read()
    text = content.decode("utf-8")
    
    from app.services.ai_engine import ai_system
    parsed_data = ai_system.parse_resume(text)
    
    # Update profile
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    if not profile:
        profile = Profile(user_id=current_user.id)
        await profile.insert()
        
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
