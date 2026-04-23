import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from beanie import PydanticObjectId

from app.api.deps import get_current_active_user
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.user import User
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


def _serialize_application_response(*, application: Application, opportunity: Opportunity) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id,
        user_id=application.user_id,
        opportunity_id=application.opportunity_id,
        opportunity_title=opportunity.title,
        opportunity_domain=opportunity.domain or "General",
        opportunity_type=opportunity.opportunity_type or "Opportunity",
        status=application.status,
        automation_mode=application.automation_mode,
        automation_log=application.automation_log,
        submitted_at=application.submitted_at,
        created_at=application.created_at,
    )

@router.get("", response_model=list[ApplicationResponse], include_in_schema=False)
@router.get("/", response_model=list[ApplicationResponse])
async def list_my_applications(
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Retrieve my applications joined with opportunity details."""
    applications = await Application.find(Application.user_id == current_user.id).sort(-Application.created_at).to_list()
    
    response_list = []
    for app in applications:
        opp = await Opportunity.get(app.opportunity_id)
        if opp:
            response_list.append(_serialize_application_response(application=app, opportunity=opp))
            
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
    """Persist an application immediately so the frontend can redirect without delay."""
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
        
    # Treat repeated apply clicks as idempotent so the frontend can still redirect.
    existing = await Application.find_one(Application.user_id == current_user.id, Application.opportunity_id == opportunity_id)
    if existing:
        return _serialize_application_response(application=existing, opportunity=opp)

    application = Application(
        user_id=current_user.id,
        opportunity_id=opportunity_id,
        status="In Progress",
        pipeline_state="applied",
        pipeline_updated_by=None,
        resume_snapshot="Saved before redirecting the user to the source opportunity page.",
        automation_mode="manual_redirect",
        automation_log=json.dumps(
            {
                "mode": "manual_redirect",
                "submitted": False,
                "summary": "Application intent saved in VidyaVerse before redirecting the user to the source page.",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=True,
        ),
        submitted_at=None,
    )
    
    await application.insert()

    try:
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
            traffic_type="real",
        )
    except Exception:
        pass
    
    return _serialize_application_response(application=application, opportunity=opp)
