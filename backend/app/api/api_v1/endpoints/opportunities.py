from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from beanie import PydanticObjectId
from beanie.exceptions import CollectionWasNotInitialized
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_active_user, get_current_admin_user
from app.core.config import settings
from app.models.application import Application
from app.models.ask_ai_query_snapshot import AskAIQuerySnapshot
from app.models.ask_ai_saved_query import AskAISavedQuery
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.traffic import TrafficType
from app.models.user import User
from app.schemas.rag import RAGAskResponse
from app.services.ai_engine import ai_system
from app.services.evaluation_service import evaluation_service
from app.services.interaction_service import interaction_service
from app.services.opportunity_visibility import (
    is_student_visible_opportunity,
    resolve_opportunity_portal,
)
from app.services.rag_service import rag_service
from app.services.recommendation_service import recommendation_service
from app.services.ranking_request_telemetry_service import ranking_request_telemetry_service
from app.core.time import utc_now

router = APIRouter()


class OpportunityCreate(BaseModel):
    title: str
    description: str
    url: str
    opportunity_type: str
    university: str
    portal_category: Optional[str] = None
    duration_start: Optional[datetime] = None
    duration_end: Optional[datetime] = None
    deadline: Optional[datetime] = None


class OpportunityResponse(OpportunityCreate):
    model_config = ConfigDict(from_attributes=True)

    id: PydanticObjectId
    domain: Optional[str] = None
    source: Optional[str] = None
    trust_status: str = "unreviewed"
    trust_score: int = 50
    risk_score: int = 50
    risk_reasons: list[str] = Field(default_factory=list)
    verification_evidence: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


class RecommendedOpportunityResponse(OpportunityResponse):
    match_score: float
    match_reasons: list[str]
    baseline_score: Optional[float] = None
    semantic_score: Optional[float] = None
    behavior_score: Optional[float] = None
    ranking_mode: Optional[str] = None
    experiment_key: Optional[str] = None
    experiment_variant: Optional[str] = None
    feature_importance_top: Optional[list[dict[str, Any]]] = None


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
    top_k: Optional[int] = Field(default=None, ge=1, le=30)


class AskAIFeedbackRequest(BaseModel):
    request_id: str = Field(min_length=1)
    query: str = Field(min_length=2)
    feedback: Literal["up", "down"]
    response_summary: Optional[str] = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    surface: str = Field(default="opportunities_page", min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    rag_template_label: Optional[str] = None
    rag_template_version_id: Optional[str] = None


class AskAISavedQueryRequest(BaseModel):
    query: str = Field(min_length=2)
    surface: str = Field(default="opportunities_page", min_length=1)


class AskAISavedQueryResponse(BaseModel):
    query: str
    surface: str
    last_used_at: datetime


class AskAIHistoryEntryResponse(BaseModel):
    request_id: str
    query: str
    surface: str
    created_at: datetime
    response_summary: Optional[str] = None
    deadline_urgency: Optional[str] = None
    recommended_action: Optional[str] = None
    citation_count: int = 0
    top_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1


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
        portal_category=resolve_opportunity_portal(
            opportunity_type=opportunity.opportunity_type,
            title=opportunity.title,
            description=opportunity.description,
            portal_category=getattr(opportunity, "portal_category", None),
        ),
        duration_start=getattr(opportunity, "duration_start", None),
        duration_end=getattr(opportunity, "duration_end", None),
        deadline=opportunity.deadline,
        domain=opportunity.domain,
        source=opportunity.source,
        trust_status=getattr(opportunity, "trust_status", "unreviewed"),
        trust_score=int(getattr(opportunity, "trust_score", 50) or 50),
        risk_score=int(getattr(opportunity, "risk_score", 50) or 50),
        risk_reasons=list(getattr(opportunity, "risk_reasons", []) or []),
        verification_evidence=list(getattr(opportunity, "verification_evidence", []) or []),
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
        feature_importance_top=payload.get("feature_importance_top"),
    )


def _activity_sort_key(opportunity: Opportunity) -> tuple[datetime, datetime]:
    latest_touch = opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at
    created_at = opportunity.created_at or latest_touch or datetime.min
    return latest_touch or datetime.min, created_at


def _filter_active_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    active = []
    for opportunity in opportunities:
        if not is_student_visible_opportunity(opportunity):
            continue
        active.append(opportunity)
    active.sort(key=_activity_sort_key, reverse=True)
    return active


def _freshness_seconds(opportunities: list[Opportunity]) -> float | None:
    now = utc_now()
    freshness_values: list[float] = []
    for opportunity in opportunities:
        last = opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at
        if last is None:
            continue
        freshness_values.append(max(0.0, (now - last).total_seconds()))
    if not freshness_values:
        return None
    return float(sum(freshness_values) / len(freshness_values))


def _extract_ask_ai_top_opportunities(result: dict[str, Any]) -> list[dict[str, Any]]:
    insights = result.get("insights") or {}
    top_rows = insights.get("top_opportunities")
    if not isinstance(top_rows, list):
        return []

    payload_rows: list[dict[str, Any]] = []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        payload_rows.append(
            {
                "opportunity_id": str(row.get("opportunity_id") or ""),
                "title": str(row.get("title") or ""),
                "why_fit": str(row.get("why_fit") or ""),
                "urgency": str(row.get("urgency") or ""),
                "match_score": float(row.get("match_score") or 0.0),
            }
        )
    return payload_rows


async def _upsert_saved_query(user_id: PydanticObjectId, query: str, surface: str) -> None:
    normalized_query = query.strip()
    normalized_surface = surface.strip() or "opportunities_page"
    if len(normalized_query) < 2:
        return

    existing = await AskAISavedQuery.find_one(
        {
            "user_id": user_id,
            "surface": normalized_surface,
            "query": normalized_query,
        }
    )
    if existing:
        existing.last_used_at = utc_now()
        await existing.save()
        return

    await AskAISavedQuery(
        user_id=user_id,
        query=normalized_query,
        surface=normalized_surface,
    ).insert()


async def _load_active_opportunities(
    *,
    domain: Optional[str] = None,
    portal: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Opportunity]:
    safe_skip = max(0, skip)
    safe_limit = max(1, min(limit, 200))
    fetch_window = min(max((safe_skip + safe_limit) * 10, 250), 2000)
    query = Opportunity.find_many(Opportunity.domain == domain) if domain else Opportunity.find_many()
    candidates = await query.sort("-created_at").limit(fetch_window).to_list()
    active = _filter_active_opportunities(candidates)
    normalized_portal = str(portal or "").strip().lower()
    if normalized_portal in {"career", "competitive", "other"}:
        active = [
            item
            for item in active
            if resolve_opportunity_portal(
                opportunity_type=item.opportunity_type,
                title=item.title,
                description=item.description,
                portal_category=getattr(item, "portal_category", None),
            )
            == normalized_portal
        ]
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
    if latest_seen < utc_now() - stale_after:
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
    portal: Optional[Literal["career", "competitive", "other"]] = None,
) -> Any:
    """
    Retrieve opportunities. Can filter by domain.
    """
    await _ensure_live_feed_if_stale()
    return await _load_active_opportunities(domain=domain, portal=portal, skip=skip, limit=limit)


@router.get("/recommended/me", response_model=list[RecommendedOpportunityResponse])
async def get_personalized_recommendations(
    limit: int = 10,
    ranking_mode: Literal["baseline", "semantic", "ml", "ab"] = "ml",
    query: Optional[str] = None,
    portal: Optional[Literal["career", "competitive", "other"]] = None,
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
        if portal:
            opportunities = [
                item
                for item in opportunities
                if resolve_opportunity_portal(
                    opportunity_type=item.opportunity_type,
                    title=item.title,
                    description=item.description,
                    portal_category=getattr(item, "portal_category", None),
                )
                == portal
            ]

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
                            "geo_match_score": item.get("geo_match_score"),
                            "source_trust": item.get("source_trust"),
                            "sequence_ctr_30d": item.get("sequence_ctr_30d"),
                            "user_recent_interactions_30d": item.get("user_recent_interactions_30d"),
                            "ranker_features": item.get("ranker_features"),
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
            requested_ranking_mode=str(meta.get("requested_mode") or requested_mode),
            ranking_mode=effective_mode,
            experiment_key=experiment_key,
            experiment_variant=experiment_variant,
            rollout_variant=(meta.get("rollout") or {}).get("variant"),
            rollout_bucket=(meta.get("rollout") or {}).get("bucket"),
            rollout_percent=(meta.get("rollout") or {}).get("percent"),
            shadow_mode=(meta.get("shadow") or {}).get("mode"),
            shadow_model_version_id=(meta.get("shadow") or {}).get("model_version_id"),
            shadow_candidate_count=int((meta.get("shadow") or {}).get("candidate_count") or 0),
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
            requested_ranking_mode=requested_mode,
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
    ranking_mode: Literal["baseline", "semantic", "ml", "ab"] = "ml",
    query: Optional[str] = None,
    portal: Optional[Literal["career", "competitive", "other"]] = None,
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
        if portal:
            opportunities = [
                item
                for item in opportunities
                if resolve_opportunity_portal(
                    opportunity_type=item.opportunity_type,
                    title=item.title,
                    description=item.description,
                    portal_category=getattr(item, "portal_category", None),
                )
                == portal
            ]
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
                            "geo_match_score": item.get("geo_match_score"),
                            "source_trust": item.get("source_trust"),
                            "sequence_ctr_30d": item.get("sequence_ctr_30d"),
                            "user_recent_interactions_30d": item.get("user_recent_interactions_30d"),
                            "ranker_features": item.get("ranker_features"),
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
            requested_ranking_mode=str(meta.get("requested_mode") or requested_mode),
            ranking_mode=effective_mode,
            experiment_key=experiment_key,
            experiment_variant=experiment_variant,
            rollout_variant=(meta.get("rollout") or {}).get("variant"),
            rollout_bucket=(meta.get("rollout") or {}).get("bucket"),
            rollout_percent=(meta.get("rollout") or {}).get("percent"),
            shadow_mode=(meta.get("shadow") or {}).get("mode"),
            shadow_model_version_id=(meta.get("shadow") or {}).get("model_version_id"),
            shadow_candidate_count=int((meta.get("shadow") or {}).get("candidate_count") or 0),
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
            requested_ranking_mode=requested_mode,
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


@router.get("/ask-ai/history", response_model=list[AskAIHistoryEntryResponse])
async def get_ask_ai_history(
    limit: int = 40,
    surface: str = "opportunities_page",
    current_user: User = Depends(get_current_active_user),
) -> Any:
    safe_limit = max(1, min(limit, 100))
    normalized_surface = surface.strip() or "opportunities_page"
    rows = (
        await AskAIQuerySnapshot.find(
            {
                "user_id": current_user.id,
                "surface": normalized_surface,
            }
        )
        .sort("-created_at")
        .limit(safe_limit)
        .to_list()
    )
    return [
        AskAIHistoryEntryResponse(
            request_id=row.request_id,
            query=row.query,
            surface=row.surface,
            created_at=row.created_at,
            response_summary=row.response_summary,
            deadline_urgency=row.deadline_urgency,
            recommended_action=row.recommended_action,
            citation_count=row.citation_count,
            top_opportunities=row.top_opportunities,
            metadata=row.metadata,
            schema_version=row.schema_version,
        )
        for row in rows
    ]


@router.get("/ask-ai/saved-queries", response_model=list[AskAISavedQueryResponse])
async def get_ask_ai_saved_queries(
    limit: int = 12,
    surface: str = "opportunities_page",
    current_user: User = Depends(get_current_active_user),
) -> Any:
    safe_limit = max(1, min(limit, 50))
    normalized_surface = surface.strip() or "opportunities_page"
    rows = (
        await AskAISavedQuery.find(
            {
                "user_id": current_user.id,
                "surface": normalized_surface,
            }
        )
        .sort("-last_used_at")
        .limit(safe_limit)
        .to_list()
    )
    return [
        AskAISavedQueryResponse(
            query=row.query,
            surface=row.surface,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.post("/ask-ai/saved-queries", response_model=AskAISavedQueryResponse)
async def save_ask_ai_query(
    payload: AskAISavedQueryRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    normalized_query = payload.query.strip()
    if len(normalized_query) < 2:
        raise HTTPException(status_code=400, detail="query must have at least 2 characters")
    normalized_surface = payload.surface.strip() or "opportunities_page"

    await _upsert_saved_query(current_user.id, normalized_query, normalized_surface)
    row = await AskAISavedQuery.find_one(
        {
            "user_id": current_user.id,
            "surface": normalized_surface,
            "query": normalized_query,
        }
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Unable to save query")
    return AskAISavedQueryResponse(query=row.query, surface=row.surface, last_used_at=row.last_used_at)


@router.post("/ask-ai", response_model=RAGAskResponse)
async def ask_ai_shortlist(
    request: AskAIRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    started_at = time.perf_counter()
    try:
        profile = await _get_or_create_profile(current_user.id)
        result = await rag_service.ask(
            query=request.query,
            top_k=request.top_k,
            profile=profile,
            user_id=current_user.id,
        )
        governance = dict(result.get("governance") or {})
        normalized_query = request.query.strip()
        try:
            await _upsert_saved_query(current_user.id, normalized_query, "opportunities_page")
        except CollectionWasNotInitialized:
            # Unit tests that call this endpoint directly can skip document persistence.
            pass

        request_id = str(result.get("request_id") or "").strip()
        if request_id:
            insights = dict(result.get("insights") or {})
            try:
                snapshot = AskAIQuerySnapshot(
                    user_id=current_user.id,
                    request_id=request_id,
                    surface="opportunities_page",
                    query=normalized_query,
                    schema_version=1,
                    response_summary=str(insights.get("summary") or "") or None,
                    deadline_urgency=str(insights.get("deadline_urgency") or "") or None,
                    recommended_action=str(insights.get("recommended_action") or "") or None,
                    citation_count=len(insights.get("citations") or []),
                    top_opportunities=_extract_ask_ai_top_opportunities(result),
                    metadata={
                        "rag_template_label": governance.get("template_label"),
                        "rag_template_version_id": governance.get("template_version_id"),
                        "experiment_key": governance.get("experiment_key"),
                        "experiment_variant": governance.get("experiment_variant"),
                    },
                )
                existing_snapshot = await AskAIQuerySnapshot.find_one(
                    {
                        "user_id": current_user.id,
                        "request_id": request_id,
                    }
                )
                if existing_snapshot:
                    existing_snapshot.query = snapshot.query
                    existing_snapshot.response_summary = snapshot.response_summary
                    existing_snapshot.deadline_urgency = snapshot.deadline_urgency
                    existing_snapshot.recommended_action = snapshot.recommended_action
                    existing_snapshot.citation_count = snapshot.citation_count
                    existing_snapshot.top_opportunities = snapshot.top_opportunities
                    existing_snapshot.metadata = snapshot.metadata
                    existing_snapshot.surface = snapshot.surface
                    existing_snapshot.schema_version = snapshot.schema_version
                    await existing_snapshot.save()
                else:
                    await snapshot.insert()
            except CollectionWasNotInitialized:
                # Unit tests that call this endpoint directly can skip document persistence.
                pass

        await ranking_request_telemetry_service.log(
            request_kind="ask_ai",
            surface="ask_ai",
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            success=True,
            user_id=current_user.id,
            results_count=len(result.get("results") or []),
            experiment_key=(governance.get("experiment_key") or "ask_ai_rag_template"),
            experiment_variant=(governance.get("experiment_variant") or governance.get("template_label")),
            rag_template_label=governance.get("template_label"),
            rag_template_version_id=governance.get("template_version_id"),
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
    metadata = dict(payload.metadata or {})
    rag_template_label = (
        (payload.rag_template_label or "").strip()
        or str(metadata.get("rag_template_label") or "").strip()
        or str(metadata.get("template_label") or "").strip()
        or None
    )
    rag_template_version_id = (
        (payload.rag_template_version_id or "").strip()
        or str(metadata.get("rag_template_version_id") or "").strip()
        or str(metadata.get("template_version_id") or "").strip()
        or None
    )
    if rag_template_label and "rag_template_label" not in metadata:
        metadata["rag_template_label"] = rag_template_label
    if rag_template_version_id and "rag_template_version_id" not in metadata:
        metadata["rag_template_version_id"] = rag_template_version_id

    event = RAGFeedbackEvent(
        user_id=current_user.id,
        request_id=payload.request_id,
        query=payload.query,
        feedback=payload.feedback,
        rag_template_label=rag_template_label,
        rag_template_version_id=rag_template_version_id,
        response_summary=payload.response_summary,
        citations=payload.citations,
        surface=payload.surface,
        metadata=metadata,
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
