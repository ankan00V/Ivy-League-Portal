from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user, get_current_admin_user
from app.core.config import settings
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User
from app.services.ai_engine import ai_system
from app.services.evaluation_service import evaluation_service
from app.services.interaction_service import interaction_service
from app.services.rag_service import rag_service
from app.services.recommendation_service import recommendation_service

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
    baseline_score: Optional[float] = None
    semantic_score: Optional[float] = None
    behavior_score: Optional[float] = None
    ranking_mode: Optional[str] = None


class InteractionEventCreate(BaseModel):
    opportunity_id: PydanticObjectId
    interaction_type: str = Field(default="click")
    ranking_mode: Optional[str] = None
    query: Optional[str] = None


class AskAIRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = 8


class RankingEvaluationRequest(BaseModel):
    query: str = Field(min_length=2)
    relevant_opportunity_ids: list[str]
    k: int = 10


class LLMEvaluationRequest(BaseModel):
    generated_text: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_output: Optional[str] = None


def _to_recommended_response(payload: dict[str, Any]) -> RecommendedOpportunityResponse:
    opportunity: Opportunity = payload["opportunity"]
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
        match_score=float(payload.get("match_score") or 0.0),
        match_reasons=list(payload.get("match_reasons") or []),
        baseline_score=payload.get("baseline_score"),
        semantic_score=payload.get("semantic_score"),
        behavior_score=payload.get("behavior_score"),
        ranking_mode=payload.get("ranking_mode"),
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

    if not settings.SCRAPER_ON_DEMAND_REFRESH_ENABLED:
        return

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

    stale_after = timedelta(minutes=max(1, settings.SCRAPER_MAX_STALENESS_MINUTES))
    if latest_seen < datetime.utcnow() - stale_after:
        asyncio.create_task(run_scheduled_scrapers())


async def _get_or_create_profile(user_id: PydanticObjectId) -> Profile:
    profile = await Profile.find_one(Profile.user_id == user_id)
    if profile:
        return profile

    profile = Profile(user_id=user_id)
    await profile.insert()
    return profile


@router.get("", response_model=list[OpportunityResponse], include_in_schema=False)
@router.get("/", response_model=list[OpportunityResponse])
async def read_opportunities(
    skip: int = 0,
    limit: int = 100,
    domain: Optional[str] = None,
) -> Any:
    """
    Retrieve opportunities. Can filter by domain.
    """
    await _ensure_live_feed_if_stale()
    return await _load_active_opportunities(domain=domain, skip=skip, limit=limit)


@router.get("/recommended/me", response_model=list[RecommendedOpportunityResponse])
async def get_personalized_recommendations(
    limit: int = 10,
    ranking_mode: str = "semantic",
    query: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Personalized recommendations with baseline + semantic + behavior-aware scoring.
    ranking_mode: baseline | semantic | ab
    """
    safe_limit = max(1, min(limit, 50))
    profile = await _get_or_create_profile(current_user.id)
    opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())

    ranked, effective_mode = await recommendation_service.rank(
        user_id=current_user.id,
        profile=profile,
        opportunities=opportunities,
        limit=safe_limit,
        ranking_mode=ranking_mode,
        query=query,
    )

    if ranked:
        await interaction_service.log_impressions(
            user_id=current_user.id,
            opportunity_ids=[item["opportunity"].id for item in ranked],
            ranking_mode=effective_mode,
            query=query,
        )

    return [_to_recommended_response(item) for item in ranked]


@router.get("/shortlist/me", response_model=list[RecommendedOpportunityResponse])
async def get_smart_shortlist(
    limit: int = 10,
    min_score: float = 35.0,
    ranking_mode: str = "semantic",
    query: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Smart shortlisting with semantic ranking and A/B experimentation support.
    """
    safe_limit = max(1, min(limit, 50))
    profile = await _get_or_create_profile(current_user.id)

    my_apps = await Application.find(Application.user_id == current_user.id).to_list()
    applied_ids = {str(application.opportunity_id) for application in my_apps}

    opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())
    opportunities = [item for item in opportunities if str(item.id) not in applied_ids]

    ranked, effective_mode = await recommendation_service.rank(
        user_id=current_user.id,
        profile=profile,
        opportunities=opportunities,
        limit=safe_limit,
        min_score=min_score,
        ranking_mode=ranking_mode,
        query=query,
    )

    if ranked:
        await interaction_service.log_impressions(
            user_id=current_user.id,
            opportunity_ids=[item["opportunity"].id for item in ranked],
            ranking_mode=effective_mode,
            query=query,
        )

    return [_to_recommended_response(item) for item in ranked]


@router.post("/interactions", response_model=dict)
async def log_opportunity_interaction(
    payload: InteractionEventCreate,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    opportunity = await Opportunity.get(payload.opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    allowed_types = {"impression", "view", "click", "apply"}
    if payload.interaction_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid interaction_type")

    await interaction_service.log_event(
        user_id=current_user.id,
        opportunity_id=payload.opportunity_id,
        interaction_type=payload.interaction_type,
        ranking_mode=payload.ranking_mode,
        query=payload.query,
    )

    return {
        "status": "ok",
        "opportunity_id": str(payload.opportunity_id),
        "interaction_type": payload.interaction_type,
    }


@router.get("/experiments/ctr", response_model=list[dict])
async def get_ctr_by_mode(
    days: int = 30,
    _: User = Depends(get_current_admin_user),
) -> Any:
    return await interaction_service.ctr_by_mode(days=days)


@router.post("/ask-ai", response_model=dict)
async def ask_ai_shortlist(
    request: AskAIRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    profile = await _get_or_create_profile(current_user.id)
    result = await rag_service.ask(query=request.query, top_k=request.top_k, profile=profile)
    return result


@router.post("/evaluate-ranking", response_model=dict)
async def evaluate_ranking_quality(
    request: RankingEvaluationRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    profile = await _get_or_create_profile(current_user.id)
    return await evaluation_service.evaluate_ranking(
        user_id=current_user.id,
        profile=profile,
        query=request.query,
        relevant_ids=request.relevant_opportunity_ids,
        k=request.k,
    )


@router.post("/evaluate-llm", response_model=dict)
async def evaluate_llm_quality(
    request: LLMEvaluationRequest,
    _: User = Depends(get_current_active_user),
) -> Any:
    return await evaluation_service.evaluate_llm_response(
        generated_text=request.generated_text,
        expected_keywords=request.expected_keywords,
        expected_output=request.expected_output,
    )


@router.post("", response_model=OpportunityResponse, include_in_schema=False)
@router.post("/", response_model=OpportunityResponse)
async def create_opportunity(
    *,
    opportunity_in: OpportunityCreate,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    """
    Create new opportunity (Admin only). Includes AI domain classification.
    """
    classification = ai_system.classify_opportunity(opportunity_in.description)
    domain_assigned = classification["primary_domain"]

    opportunity = Opportunity(
        **opportunity_in.model_dump(),
        domain=domain_assigned,
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
