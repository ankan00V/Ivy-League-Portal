from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user, get_current_admin_user
from app.core.config import settings
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.traffic import TrafficType
from app.models.user import User
from app.schemas.rag import RAGAskResponse
from app.services.ai_engine import ai_system
from app.services.evaluation_service import evaluation_service
from app.services.interaction_service import interaction_service
from app.services.rag_service import rag_service
from app.services.recommendation_service import recommendation_service
from app.services.ranking_request_telemetry_service import ranking_request_telemetry_service

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
    experiment_key: Optional[str] = None
    experiment_variant: Optional[str] = None


class InteractionEventCreate(BaseModel):
    opportunity_id: PydanticObjectId
    interaction_type: str = Field(default="click")
    ranking_mode: Optional[str] = None
    experiment_key: Optional[str] = None
    experiment_variant: Optional[str] = None
    traffic_type: TrafficType = "real"
    query: Optional[str] = None
    model_version_id: Optional[str] = None
    rank_position: Optional[int] = None
    match_score: Optional[float] = None
    features: Optional[dict[str, Any]] = None


class AskAIRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = 8


class AskAIFeedbackRequest(BaseModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=2)
    feedback: Literal["up", "down"]
    response_summary: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    surface: str = Field(default="opportunities_page", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RankingEvaluationRequest(BaseModel):
    query: str = Field(min_length=2)
    relevant_opportunity_ids: list[str]
    k: int = 10


class LLMEvaluationRequest(BaseModel):
    generated_text: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_phrases: list[str] = Field(default_factory=list)
    expected_output: Optional[str] = None
    required_citations: list[str] = Field(default_factory=list)
    allowed_citations: list[str] = Field(default_factory=list)
    rubric_weights: Optional[dict[str, float]] = None
    include_judge: bool = False
    rubric: Optional[str] = None


def _resolve_experiment_context(*, effective_mode: str, meta: dict[str, Any]) -> tuple[str, str]:
    experiment_key = str(meta.get("experiment_key") or "ranking_mode").strip() or "ranking_mode"
    experiment_variant = str(meta.get("variant") or effective_mode).strip() or effective_mode
    return experiment_key, experiment_variant


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
        experiment_key=payload.get("experiment_key"),
        experiment_variant=payload.get("experiment_variant"),
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


def _freshness_seconds(opportunities: list[Opportunity]) -> float | None:
    now = datetime.utcnow()
    freshness_values: list[float] = []
    for opportunity in opportunities:
        last = opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at
        if last is None:
            continue
        freshness_values.append(max(0.0, (now - last).total_seconds()))
    if not freshness_values:
        return None
    return float(sum(freshness_values) / len(freshness_values))


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
    from app.services.job_runner import job_runner

    if not settings.SCRAPER_ON_DEMAND_REFRESH_ENABLED:
        return

    runtime = get_scraper_runtime_status()
    if runtime.get("is_running"):
        return

    latest_items = await Opportunity.find_many().sort("-last_seen_at").limit(1).to_list()
    if not latest_items:
        if settings.JOBS_ENABLED:
            await job_runner.enqueue(job_type="scraper.run", dedupe_key="scraper.run")
        else:
            asyncio.create_task(run_scheduled_scrapers())
        return

    latest_seen = latest_items[0].last_seen_at or latest_items[0].updated_at or latest_items[0].created_at
    if latest_seen is None:
        if settings.JOBS_ENABLED:
            await job_runner.enqueue(job_type="scraper.run", dedupe_key="scraper.run")
        else:
            asyncio.create_task(run_scheduled_scrapers())
        return

    stale_after = timedelta(minutes=max(1, settings.SCRAPER_MAX_STALENESS_MINUTES))
    if latest_seen < datetime.utcnow() - stale_after:
        if settings.JOBS_ENABLED:
            await job_runner.enqueue(job_type="scraper.run", dedupe_key="scraper.run")
        else:
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
    ranking_mode: Literal["baseline", "semantic", "ml", "ab"] = "semantic",
    query: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Personalized recommendations with baseline + semantic + behavior-aware scoring.
    ranking_mode: baseline | semantic | ml | ab
    """
    started_at = time.perf_counter()
    safe_limit = max(1, min(limit, 50))
    requested_mode = ranking_mode
    try:
        profile = await _get_or_create_profile(current_user.id)
        opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())

        ranked, meta = await recommendation_service.rank(
            user_id=current_user.id,
            profile=profile,
            opportunities=opportunities,
            limit=safe_limit,
            ranking_mode=ranking_mode,
            query=query,
        )
        effective_mode = str(meta.get("mode") or "semantic")
        experiment_key, experiment_variant = _resolve_experiment_context(
            effective_mode=effective_mode,
            meta=meta,
        )

        for item in ranked:
            item["experiment_key"] = experiment_key
            item["experiment_variant"] = experiment_variant

        if ranked:
            await interaction_service.log_impressions(
                user_id=current_user.id,
                impressions=[
                    {
                        "opportunity_id": item["opportunity"].id,
                        "ranking_mode": effective_mode,
                        "experiment_key": experiment_key,
                        "experiment_variant": experiment_variant,
                        "query": query,
                        "model_version_id": meta.get("model_version_id"),
                        "rank_position": idx + 1,
                        "match_score": item.get("match_score"),
                        "features": {
                            "baseline_score": item.get("baseline_score"),
                            "semantic_score": item.get("semantic_score"),
                            "behavior_score": item.get("behavior_score"),
                            "skills_overlap_score": item.get("skills_overlap_score"),
                            "behavior_domain_pref": item.get("behavior_domain_pref"),
                            "behavior_type_pref": item.get("behavior_type_pref"),
                        },
                    }
                    for idx, item in enumerate(ranked)
                ],
                traffic_type="real",
            )

        await ranking_request_telemetry_service.log(
            request_kind="recommended",
            surface="recommended_me",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=True,
            user_id=current_user.id,
            ranking_mode=effective_mode,
            experiment_key=experiment_key,
            experiment_variant=experiment_variant,
            model_version_id=meta.get("model_version_id"),
            results_count=len(ranked),
            freshness_seconds=_freshness_seconds([item["opportunity"] for item in ranked]),
            traffic_type="real",
        )
        return [_to_recommended_response(item) for item in ranked]
    except Exception as exc:
        await ranking_request_telemetry_service.log(
            request_kind="recommended",
            surface="recommended_me",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=False,
            user_id=current_user.id,
            ranking_mode=requested_mode,
            results_count=0,
            error_code=exc.__class__.__name__,
            traffic_type="real",
        )
        raise


@router.get("/shortlist/me", response_model=list[RecommendedOpportunityResponse])
async def get_smart_shortlist(
    limit: int = 10,
    min_score: float = 35.0,
    ranking_mode: Literal["baseline", "semantic", "ml", "ab"] = "semantic",
    query: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """
    Smart shortlisting with semantic ranking and A/B experimentation support.
    """
    started_at = time.perf_counter()
    requested_mode = ranking_mode
    safe_limit = max(1, min(limit, 50))
    try:
        profile = await _get_or_create_profile(current_user.id)

        my_apps = await Application.find(Application.user_id == current_user.id).to_list()
        applied_ids = {str(application.opportunity_id) for application in my_apps}

        opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())
        opportunities = [item for item in opportunities if str(item.id) not in applied_ids]

        ranked, meta = await recommendation_service.rank(
            user_id=current_user.id,
            profile=profile,
            opportunities=opportunities,
            limit=safe_limit,
            min_score=min_score,
            ranking_mode=ranking_mode,
            query=query,
        )
        effective_mode = str(meta.get("mode") or "semantic")
        experiment_key, experiment_variant = _resolve_experiment_context(
            effective_mode=effective_mode,
            meta=meta,
        )

        for item in ranked:
            item["experiment_key"] = experiment_key
            item["experiment_variant"] = experiment_variant

        if ranked:
            await interaction_service.log_impressions(
                user_id=current_user.id,
                impressions=[
                    {
                        "opportunity_id": item["opportunity"].id,
                        "ranking_mode": effective_mode,
                        "experiment_key": experiment_key,
                        "experiment_variant": experiment_variant,
                        "query": query,
                        "model_version_id": meta.get("model_version_id"),
                        "rank_position": idx + 1,
                        "match_score": item.get("match_score"),
                        "features": {
                            "baseline_score": item.get("baseline_score"),
                            "semantic_score": item.get("semantic_score"),
                            "behavior_score": item.get("behavior_score"),
                            "skills_overlap_score": item.get("skills_overlap_score"),
                            "behavior_domain_pref": item.get("behavior_domain_pref"),
                            "behavior_type_pref": item.get("behavior_type_pref"),
                        },
                    }
                    for idx, item in enumerate(ranked)
                ],
                traffic_type="real",
            )

        await ranking_request_telemetry_service.log(
            request_kind="shortlist",
            surface="shortlist_me",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=True,
            user_id=current_user.id,
            ranking_mode=effective_mode,
            experiment_key=experiment_key,
            experiment_variant=experiment_variant,
            model_version_id=meta.get("model_version_id"),
            results_count=len(ranked),
            freshness_seconds=_freshness_seconds([item["opportunity"] for item in ranked]),
            traffic_type="real",
        )
        return [_to_recommended_response(item) for item in ranked]
    except Exception as exc:
        await ranking_request_telemetry_service.log(
            request_kind="shortlist",
            surface="shortlist_me",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=False,
            user_id=current_user.id,
            ranking_mode=requested_mode,
            results_count=0,
            error_code=exc.__class__.__name__,
            traffic_type="real",
        )
        raise


@router.post("/interactions", response_model=dict)
async def log_opportunity_interaction(
    payload: InteractionEventCreate,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    opportunity = await Opportunity.get(payload.opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    allowed_types = {"impression", "view", "click", "apply", "save"}
    if payload.interaction_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid interaction_type")

    tracking_mode = (payload.ranking_mode or "").strip().lower() or None
    tracking_experiment_key = (payload.experiment_key or "").strip() or None
    tracking_experiment_variant = (payload.experiment_variant or "").strip() or None
    tracking_rank_position = payload.rank_position
    tracking_traffic_type = (payload.traffic_type or "real").strip().lower()
    if tracking_traffic_type not in {"real", "simulated"}:
        raise HTTPException(status_code=400, detail="Invalid traffic_type")
    if tracking_traffic_type != "real":
        # Public client endpoint should not ingest simulated events.
        raise HTTPException(status_code=400, detail="traffic_type must be 'real' for live interactions")

    if payload.interaction_type in {"impression", "click", "save", "apply"}:
        required_fields: dict[str, Any] = {
            "ranking_mode": tracking_mode,
            "experiment_key": tracking_experiment_key,
            "experiment_variant": tracking_experiment_variant,
            "rank_position": tracking_rank_position,
        }
        missing = [
            key
            for key, value in required_fields.items()
            if value is None or (isinstance(value, str) and not value.strip())
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required tracking metadata: {', '.join(missing)}",
            )

        if tracking_mode not in {"baseline", "semantic", "ml", "ab"}:
            raise HTTPException(status_code=400, detail="Invalid ranking_mode")
        if tracking_rank_position is None or int(tracking_rank_position) <= 0:
            raise HTTPException(status_code=400, detail="rank_position must be >= 1")

    await interaction_service.log_event(
        user_id=current_user.id,
        opportunity_id=payload.opportunity_id,
        interaction_type=payload.interaction_type,
        ranking_mode=tracking_mode,
        experiment_key=tracking_experiment_key,
        experiment_variant=tracking_experiment_variant,
        query=payload.query,
        model_version_id=payload.model_version_id,
        rank_position=tracking_rank_position,
        match_score=payload.match_score,
        features=payload.features,
        traffic_type="real",
    )

    return {
        "status": "ok",
        "opportunity_id": str(payload.opportunity_id),
        "interaction_type": payload.interaction_type,
    }


@router.get("/experiments/ctr", response_model=list[dict])
async def get_ctr_by_mode(
    days: int = 30,
    traffic_type: Literal["all", "real", "simulated"] = "real",
    _: User = Depends(get_current_admin_user),
) -> Any:
    return await interaction_service.ctr_by_mode(days=days, traffic_type=traffic_type)


@router.get("/experiments/lift", response_model=dict)
async def get_lift_vs_baseline(
    days: int = 30,
    baseline_mode: str = "baseline",
    traffic_type: Literal["all", "real", "simulated"] = "real",
    _: User = Depends(get_current_admin_user),
) -> Any:
    """
    Computes CTR/apply_rate/save_rate per ranking mode + lift vs baseline.
    """
    return await interaction_service.lift_vs_baseline(days=days, baseline_mode=baseline_mode, traffic_type=traffic_type)


@router.get("/ask-ai/schema", response_model=dict)
async def ask_ai_schema() -> Any:
    """
    Returns the strict JSON schema contract for the Ask-AI RAG response.
    """
    return RAGAskResponse.model_json_schema()


@router.post("/ask-ai", response_model=RAGAskResponse)
async def ask_ai_shortlist(
    request: AskAIRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    started_at = time.perf_counter()
    try:
        profile = await _get_or_create_profile(current_user.id)
        result = await rag_service.ask(query=request.query, top_k=request.top_k, profile=profile)
        await ranking_request_telemetry_service.log(
            request_kind="ask_ai",
            surface="ask_ai",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=True,
            user_id=current_user.id,
            results_count=len(result.get("results") or []),
            traffic_type="real",
        )
        return result
    except Exception as exc:
        await ranking_request_telemetry_service.log(
            request_kind="ask_ai",
            surface="ask_ai",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=False,
            user_id=current_user.id,
            error_code=exc.__class__.__name__,
            traffic_type="real",
        )
        raise


@router.post("/ask-ai/feedback", response_model=dict)
async def log_ask_ai_feedback(
    payload: AskAIFeedbackRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    event = RAGFeedbackEvent(
        user_id=current_user.id,
        request_id=payload.request_id,
        query=payload.query,
        feedback=payload.feedback,
        response_summary=payload.response_summary,
        citations=payload.citations,
        surface=payload.surface,
        metadata=payload.metadata,
    )
    await event.insert()
    return {"status": "ok", "request_id": payload.request_id, "feedback": payload.feedback}


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
        expected_phrases=request.expected_phrases,
        expected_output=request.expected_output,
        required_citations=request.required_citations,
        allowed_citations=request.allowed_citations,
        rubric_weights=request.rubric_weights,
        include_judge=request.include_judge,
        rubric=request.rubric,
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
async def trigger_scraper(
    _: User = Depends(get_current_admin_user),
) -> Any:
    """
    Trigger the resilient scraper manually to fetch remote opportunities (Unstop, Naukri) and insert into DB.
    """
    from app.services.job_runner import job_runner

    job = await job_runner.enqueue(job_type="scraper.run", dedupe_key="scraper.run.manual")

    return {
        "message": "Scraper job enqueued.",
        "job_id": str(job.id),
    }


@router.get("/scraper-status", response_model=dict)
async def scraper_status(
    _: User = Depends(get_current_active_user),
) -> Any:
    """
    Returns scraper runtime status and latest source-level ingestion report.
    """
    from app.services.scraper import get_scraper_runtime_status

    return get_scraper_runtime_status()
