import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends
from beanie import PydanticObjectId

from app.api.deps import get_current_active_user, get_current_admin_user
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User
from pydantic import BaseModel
from app.core.config import settings
from app.services.ai_engine import ai_system
from app.services.intelligence import score_opportunity_match

router = APIRouter()

class OpportunityCreate(BaseModel):
    title: str
    description: str
    url: str
    opportunity_type: str
    university: str
    deadline: Optional[datetime] = None

class OpportunityResponse(OpportunityCreate):
    id: PydanticObjectId
    domain: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class RecommendedOpportunityResponse(OpportunityResponse):
    match_score: float
    match_reasons: list[str]


def _to_recommended_response(
    opportunity: Opportunity, match_score: float, match_reasons: list[str]
) -> RecommendedOpportunityResponse:
    return RecommendedOpportunityResponse(
        id=opportunity.id,
        title=opportunity.title,
        description=opportunity.description,
        url=opportunity.url,
        opportunity_type=opportunity.opportunity_type or "Opportunity",
        university=opportunity.university or "Unknown",
        deadline=opportunity.deadline,
        domain=opportunity.domain,
        source=opportunity.source,
        created_at=opportunity.created_at,
        updated_at=opportunity.updated_at,
        last_seen_at=opportunity.last_seen_at,
        match_score=match_score,
        match_reasons=match_reasons,
    )


def _activity_sort_key(opportunity: Opportunity) -> tuple[datetime, datetime]:
    latest_touch = opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at
    created_at = opportunity.created_at or latest_touch or datetime.min
    return latest_touch or datetime.min, created_at


def _filter_active_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    from app.services.scraper import is_opportunity_active

    active = [opportunity for opportunity in opportunities if is_opportunity_active(opportunity)]
    active.sort(key=_activity_sort_key, reverse=True)
    return active


async def _load_active_opportunities(
    *,
    domain: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Opportunity]:
    safe_skip = max(0, skip)
    safe_limit = max(1, min(limit, 200))
    fetch_window = min(max((safe_skip + safe_limit) * 10, 250), 2000)
    query = Opportunity.find_many(Opportunity.domain == domain) if domain else Opportunity.find_many()
    candidates = await query.sort("-created_at").limit(fetch_window).to_list()
    active = _filter_active_opportunities(candidates)
    return active[safe_skip : safe_skip + safe_limit]


async def _ensure_live_feed_if_stale() -> None:
    from app.services.scraper import get_scraper_runtime_status, run_scheduled_scrapers

    runtime = get_scraper_runtime_status()
    if runtime.get("is_running"):
        return

    latest_items = await Opportunity.find_many().sort("-last_seen_at").limit(1).to_list()
    if not latest_items:
        asyncio.create_task(run_scheduled_scrapers())
        return

    latest_seen = latest_items[0].last_seen_at or latest_items[0].updated_at or latest_items[0].created_at
    if latest_seen is None:
        asyncio.create_task(run_scheduled_scrapers())
        return

    stale_after = timedelta(minutes=max(2, settings.SCRAPER_INTERVAL_MINUTES * 2))
    if latest_seen < datetime.utcnow() - stale_after:
        asyncio.create_task(run_scheduled_scrapers())


@router.get("", response_model=list[OpportunityResponse], include_in_schema=False)
@router.get("/", response_model=list[OpportunityResponse])
async def read_opportunities(
    skip: int = 0,
    limit: int = 100,
    domain: Optional[str] = None
) -> Any:
    """
    Retrieve opportunities. Can filter by domain.
    """
    await _ensure_live_feed_if_stale()
    return await _load_active_opportunities(domain=domain, skip=skip, limit=limit)


@router.get("/recommended/me", response_model=list[RecommendedOpportunityResponse])
async def get_personalized_recommendations(
    limit: int = 10,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Personalized opportunity feed based on profile skills, interests and InCoScore context.
    """
    safe_limit = max(1, min(limit, 50))
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    if not profile:
        profile = Profile(user_id=current_user.id)
        await profile.insert()

    opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())
    ranked: list[tuple[float, list[str], Opportunity]] = []
    for opportunity in opportunities:
        score, reasons = score_opportunity_match(profile, opportunity)
        ranked.append((score, reasons, opportunity))

    ranked.sort(key=lambda item: (item[0], *_activity_sort_key(item[2])), reverse=True)
    return [
        _to_recommended_response(opportunity=item[2], match_score=item[0], match_reasons=item[1])
        for item in ranked[:safe_limit]
    ]


@router.get("/shortlist/me", response_model=list[RecommendedOpportunityResponse])
async def get_smart_shortlist(
    limit: int = 10,
    min_score: float = 35.0,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Smart shortlisting endpoint that filters opportunities the student is most likely to qualify for.
    """
    safe_limit = max(1, min(limit, 50))
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    if not profile:
        profile = Profile(user_id=current_user.id)
        await profile.insert()

    my_apps = await Application.find(Application.user_id == current_user.id).to_list()
    applied_ids = {str(application.opportunity_id) for application in my_apps}

    opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())
    shortlisted: list[tuple[float, list[str], Opportunity]] = []
    for opportunity in opportunities:
        if str(opportunity.id) in applied_ids:
            continue
        score, reasons = score_opportunity_match(profile, opportunity)
        if score >= min_score:
            shortlisted.append((score, reasons, opportunity))

    shortlisted.sort(key=lambda item: (item[0], *_activity_sort_key(item[2])), reverse=True)
    return [
        _to_recommended_response(opportunity=item[2], match_score=item[0], match_reasons=item[1])
        for item in shortlisted[:safe_limit]
    ]

@router.post("", response_model=OpportunityResponse, include_in_schema=False)
@router.post("/", response_model=OpportunityResponse)
async def create_opportunity(
    *,
    opportunity_in: OpportunityCreate,
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """
    Create new opportunity (Admin only). Includes AI domain classification.
    """
    # Use AI to classify domain
    classification = ai_system.classify_opportunity(opportunity_in.description)
    domain_assigned = classification["primary_domain"]
    
    opportunity = Opportunity(
        **opportunity_in.model_dump(),
        domain=domain_assigned
    )
    await opportunity.insert()
    return opportunity

@router.post("/trigger-scraper", response_model=dict)
async def trigger_scraper() -> Any:
    """
    Trigger the resilient scraper manually to fetch remote opportunities (Unstop, Naukri) and insert into DB.
    """
    from app.services.scraper import run_scheduled_scrapers

    report = await run_scheduled_scrapers()

    return {
        "message": "Scraper triggered successfully.",
        "report": report,
    }


@router.get("/scraper-status", response_model=dict)
async def scraper_status() -> Any:
    """
    Returns scraper runtime status and latest source-level ingestion report.
    """
    from app.services.scraper import get_scraper_runtime_status

    return get_scraper_runtime_status()
