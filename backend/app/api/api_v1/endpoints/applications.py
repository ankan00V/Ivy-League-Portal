from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from beanie import PydanticObjectId

from app.api.deps import get_current_active_user
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User
from app.services.auto_apply import auto_apply_with_playwright, serialize_automation_log
from app.services.interaction_service import interaction_service

router = APIRouter()

class ApplicationResponse(BaseModel):
    id: PydanticObjectId
    user_id: PydanticObjectId
    opportunity_id: PydanticObjectId
    opportunity_title: str
    opportunity_domain: str
    opportunity_type: str
    status: str
    automation_mode: Optional[str] = None
    automation_log: Optional[str] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

@router.get("", response_model=list[ApplicationResponse], include_in_schema=False)
@router.get("/", response_model=list[ApplicationResponse])
async def list_my_applications(
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Retrieve my applications joined with opportunity details."""
    applications = await Application.find(Application.user_id == current_user.id).to_list()
    
    response_list = []
    for app in applications:
        opp = await Opportunity.get(app.opportunity_id)
        if opp:
            response_list.append(ApplicationResponse(
                id=app.id,
                user_id=app.user_id,
                opportunity_id=app.opportunity_id,
                opportunity_title=opp.title,
                opportunity_domain=opp.domain or "General",
                opportunity_type=opp.opportunity_type or "Opportunity",
                status=app.status,
                automation_mode=app.automation_mode,
                automation_log=app.automation_log,
                submitted_at=app.submitted_at,
                created_at=app.created_at
            ))
            
    return response_list

@router.post("/{opportunity_id}", response_model=ApplicationResponse)
async def apply_to_opportunity(
    opportunity_id: PydanticObjectId,
    ranking_mode: Optional[str] = None,
    experiment_key: Optional[str] = None,
    experiment_variant: Optional[str] = None,
    rank_position: Optional[int] = None,
    match_score: Optional[float] = None,
    model_version_id: Optional[str] = None,
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Automated application submission using Playwright browser automation."""
    tracking_mode = (ranking_mode or "baseline").strip().lower()
    if tracking_mode not in {"baseline", "semantic", "ml", "ab"}:
        raise HTTPException(status_code=400, detail="Invalid ranking_mode")

    tracking_experiment_key = (experiment_key or "ranking_mode").strip()
    if not tracking_experiment_key:
        raise HTTPException(status_code=400, detail="experiment_key must not be empty")

    tracking_experiment_variant = (experiment_variant or tracking_mode).strip()
    if not tracking_experiment_variant:
        raise HTTPException(status_code=400, detail="experiment_variant must not be empty")

    tracking_rank_position = int(rank_position or 1)
    if tracking_rank_position <= 0:
        raise HTTPException(status_code=400, detail="rank_position must be >= 1")

    # Verify opportunity exists
    opp = await Opportunity.get(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
        
    # Check if already applied
    existing = await Application.find_one(Application.user_id == current_user.id, Application.opportunity_id == opportunity_id)
    if existing:
        raise HTTPException(status_code=400, detail="Already applied to this opportunity")

    profile = await Profile.find_one(Profile.user_id == current_user.id)
    automation_result = await auto_apply_with_playwright(opportunity=opp, user=current_user, profile=profile)
    if automation_result.get("submitted"):
        status = "Submitted"
        submitted_at = datetime.now(timezone.utc)
    elif automation_result.get("filled_fields", 0) > 0:
        status = "Auto-Filled"
        submitted_at = None
    else:
        status = "Pending Manual"
        submitted_at = None

    automation_log = serialize_automation_log(automation_result)

    application = Application(
        user_id=current_user.id,
        opportunity_id=opportunity_id,
        status=status,
        resume_snapshot="Auto-filled using profile context and browser automation",
        automation_mode=automation_result.get("mode"),
        automation_log=automation_log,
        submitted_at=submitted_at,
    )
    
    await application.insert()

    await interaction_service.log_event(
        user_id=current_user.id,
        opportunity_id=opp.id,
        interaction_type="apply",
        ranking_mode=tracking_mode,
        experiment_key=tracking_experiment_key,
        experiment_variant=tracking_experiment_variant,
        rank_position=tracking_rank_position,
        match_score=match_score,
        model_version_id=model_version_id,
    )
    
    return ApplicationResponse(
        id=application.id,
        user_id=application.user_id,
        opportunity_id=application.opportunity_id,
        opportunity_title=opp.title,
        opportunity_domain=opp.domain or "General",
        opportunity_type=opp.opportunity_type or "Opportunity",
        status=application.status,
        automation_mode=application.automation_mode,
        automation_log=application.automation_log,
        submitted_at=application.submitted_at,
        created_at=application.created_at
    )
