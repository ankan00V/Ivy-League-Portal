from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import get_current_admin_user
from app.models.auth_audit_event import AuthAuditEvent
from app.models.background_job import BackgroundJob
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.models.scraper_run_log import ScraperRunLog
from app.models.source_discovery import ScraperRegistration, ScraperRegistrationStatus
from app.models.post import Comment as SocialComment
from app.models.post import Post
from app.models.user import User
from app.core.redis import get_redis
from app.core.time import utc_now
from app.services.auth_security_service import auth_security_service
from app.services.job_runner import job_runner
from app.services.ranking_model_service import ranking_model_service
from app.services.opportunity_visibility import (
    canonical_opportunity_type,
    is_opportunity_expired,
    is_student_visible_opportunity,
    resolve_opportunity_portal,
)
from app.services.opportunity_trust import (
    TRUST_STATUS_BLOCKED,
    TRUST_STATUS_NEEDS_REVIEW,
    TRUST_STATUS_UNREVIEWED,
    TRUST_STATUS_VERIFIED,
    apply_trust_assessment,
    assess_opportunity_trust,
)

router = APIRouter(include_in_schema=False)


def _request_context(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    ip_address: Optional[str] = None
    if request.client and request.client.host:
        ip_address = str(request.client.host)
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


async def _audit_admin_action(
    *,
    action: str,
    actor: User,
    success: bool,
    reason_payload: dict[str, Any] | None = None,
    request: Optional[Request] = None,
) -> None:
    ip_address, user_agent = _request_context(request)
    reason = json.dumps(reason_payload or {}, separators=(",", ":"), default=str)
    await auth_security_service.audit_event(
        event_type=f"admin.{action}".strip("."),
        email=str(getattr(actor, "email", "") or "").strip().lower() or None,
        account_type=str(getattr(actor, "account_type", "candidate") or "candidate"),
        purpose="admin",
        success=success,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=actor.id,
    )


class AdminOverviewResponse(BaseModel):
    users_total: int
    active_users: int
    opportunities_total: int
    active_opportunities_total: int
    expired_opportunities_total: int
    inactive_opportunities_total: int
    verified_opportunities_total: int
    needs_review_opportunities_total: int
    blocked_opportunities_total: int
    social_posts_total: int
    social_comments_total: int
    jobs_dead_count: int
    generated_at: datetime


class AdminOpportunityCreate(BaseModel):
    title: str
    description: str
    url: str
    opportunity_type: str = "Job"
    university: str = "Unknown"
    domain: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    work_mode: Optional[str] = None
    quality_score: Optional[float] = None
    eligibility: Optional[str] = None
    ppo_available: Optional[str] = None
    duration_start: datetime
    duration_end: datetime
    deadline: datetime
    lifecycle_status: str = "published"
    trust_status: Optional[str] = None
    verification_evidence: list[str] = Field(default_factory=list)


class AdminOpportunityUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    opportunity_type: Optional[str] = None
    university: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    eligibility: Optional[str] = None
    ppo_available: Optional[str] = None
    duration_start: Optional[datetime] = None
    duration_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    lifecycle_status: Optional[str] = None
    trust_status: Optional[str] = None
    verification_evidence: Optional[list[str]] = None


class AdminOpportunityResponse(BaseModel):
    id: str
    title: str
    description: str
    url: str
    opportunity_type: Optional[str] = None
    portal_category: str
    university: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    eligibility: Optional[str] = None
    ppo_available: Optional[str] = None
    trust_status: str
    trust_score: int
    risk_score: int
    risk_reasons: list[str]
    verification_evidence: list[str]
    lifecycle_status: str
    opportunity_status: str
    freshness_score: float
    duration_start: Optional[datetime] = None
    duration_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    is_expired: bool
    visible_on_student_portal: bool
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime


class AdminPostResponse(BaseModel):
    id: str
    user_id: str
    domain: str
    content: str
    likes_count: int
    created_at: datetime


class AdminCommentResponse(BaseModel):
    id: str
    post_id: str
    user_id: str
    content: str
    created_at: datetime


class AdminUserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    username: Optional[str] = None
    account_type: str
    auth_provider: str
    is_active: bool
    is_admin: bool
    created_at: datetime


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserRoleUpdate(BaseModel):
    account_type: Optional[str] = Field(default=None, pattern="^(candidate|employer)$")
    is_admin: Optional[bool] = None


class AdminJobEnqueueRequest(BaseModel):
    job_type: str = Field(min_length=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1, le=50)
    dedupe_key: Optional[str] = None


class AdminAuthUnlockRequest(BaseModel):
    email: EmailStr
    action: Optional[str] = None
    purpose: Optional[str] = None


class AdminOpportunityStatusUpdate(BaseModel):
    status: str = Field(pattern="^(active|closing_soon|expired|filled|removed)$")


class AdminQualityPipelineRequest(BaseModel):
    stale_days: int = Field(default=7, ge=1, le=365)
    limit: Optional[int] = Field(default=None, ge=1, le=100_000)
    enqueue: bool = True


class AdminDedupRunRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=100_000)
    execute: bool = False
    mark_duplicate_closed: bool = False
    enqueue: bool = True


class AdminTrainRankerRequest(BaseModel):
    lookback_days: int = Field(default=120, ge=1, le=365)
    min_rows: int = Field(default=100, ge=50, le=5_000_000)
    auto_activate: bool = False
    enqueue: bool = True


def _opportunity_payload(row: Opportunity) -> AdminOpportunityResponse:
    portal_category = resolve_opportunity_portal(
        opportunity_type=row.opportunity_type,
        title=row.title,
        description=row.description,
        portal_category=row.portal_category,
    )
    return AdminOpportunityResponse(
        id=str(row.id),
        title=row.title,
        description=row.description,
        url=row.url,
        opportunity_type=row.opportunity_type,
        portal_category=portal_category,
        university=row.university,
        domain=row.domain,
        source=row.source,
        location=row.location,
        work_mode=row.work_mode,
        quality_score=row.quality_score,
        eligibility=row.eligibility,
        ppo_available=row.ppo_available,
        trust_status=row.trust_status or TRUST_STATUS_UNREVIEWED,
        trust_score=int(row.trust_score or 0),
        risk_score=int(row.risk_score or 0),
        risk_reasons=list(row.risk_reasons or []),
        verification_evidence=list(row.verification_evidence or []),
        lifecycle_status=row.lifecycle_status or "published",
        opportunity_status=getattr(row, "opportunity_status", "active") or "active",
        freshness_score=float(getattr(row, "freshness_score", 1.0) or 0.0),
        duration_start=row.duration_start,
        duration_end=row.duration_end,
        deadline=row.deadline,
        is_expired=is_opportunity_expired(row),
        visible_on_student_portal=is_student_visible_opportunity(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
    )


def _validate_lifecycle_status(value: str) -> str:
    lifecycle_status = str(value or "published").strip().lower()
    if lifecycle_status not in {"draft", "published", "paused", "closed"}:
        raise HTTPException(status_code=400, detail="Invalid lifecycle_status")
    return lifecycle_status


def _validate_opportunity_status(value: str) -> str:
    status = str(value or "active").strip().lower()
    if status not in {"active", "closing_soon", "expired", "filled", "removed"}:
        raise HTTPException(status_code=400, detail="Invalid opportunity status")
    return status


def _validate_trust_status(value: str) -> str:
    trust_status = str(value or TRUST_STATUS_UNREVIEWED).strip().lower()
    if trust_status not in {
        TRUST_STATUS_VERIFIED,
        TRUST_STATUS_UNREVIEWED,
        TRUST_STATUS_NEEDS_REVIEW,
        TRUST_STATUS_BLOCKED,
    }:
        raise HTTPException(status_code=400, detail="Invalid trust_status")
    return trust_status


def _normalize_ppo_available(value: Optional[str]) -> Optional[str]:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    if candidate not in {"yes", "no", "undefined"}:
        raise HTTPException(status_code=400, detail="ppo_available must be yes, no, or undefined")
    return candidate


def _apply_lifecycle_status(row: Opportunity, lifecycle_status: str) -> None:
    now = utc_now()
    row.lifecycle_status = lifecycle_status
    row.lifecycle_updated_at = now
    if lifecycle_status == "published":
        row.published_at = row.published_at or now
        row.paused_at = None
        row.closed_at = None
    elif lifecycle_status == "paused":
        row.paused_at = now
    elif lifecycle_status == "closed":
        row.closed_at = now


def _admin_user_payload(row: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=str(row.id),
        email=row.email,
        full_name=row.full_name,
        username=row.username,
        account_type=row.account_type,
        auth_provider=row.auth_provider,
        is_active=bool(row.is_active),
        is_admin=bool(row.is_admin),
        created_at=row.created_at,
    )


@router.get("/system/health", response_model=dict)
async def admin_system_health(_: User = Depends(get_current_admin_user)) -> Any:
    redis_status = "disabled"
    try:
        redis = get_redis()
        if redis is not None:
            await redis.ping()
            redis_status = "up"
    except Exception:
        redis_status = "down"

    opportunities_total = await Opportunity.find_many().count()
    users_total = await User.find_many().count()
    pending_jobs = await BackgroundJob.find_many(BackgroundJob.status == "pending").count()
    dead_jobs = await BackgroundJob.find_many(BackgroundJob.status == "dead").count()
    return {
        "status": "healthy" if redis_status != "down" else "degraded",
        "generated_at": utc_now().isoformat(),
        "components": {
            "mongodb": {"status": "up"},
            "redis": {"status": redis_status},
            "jobs": {"pending": int(pending_jobs), "dead": int(dead_jobs)},
        },
        "summary": {
            "users_total": int(users_total),
            "opportunities_total": int(opportunities_total),
        },
    }


@router.post("/auth/unlock", response_model=dict)
async def admin_unlock_auth_subject(
    payload: AdminAuthUnlockRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    cleared = await auth_security_service.clear_locks(
        email=str(payload.email),
        action=payload.action,
        purpose=payload.purpose,
    )
    await _audit_admin_action(
        action="auth.unlock",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={
            "email": str(payload.email).lower(),
            "action": payload.action,
            "purpose": payload.purpose,
            "cleared": cleared,
        },
    )
    return {"status": "ok", "cleared": cleared}


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    _: User = Depends(get_current_admin_user),
) -> Any:
    users_total = await User.find_many().count()
    active_users = await User.find_many(User.is_active == True).count()  # noqa: E712
    opportunities = await Opportunity.find_many().to_list()
    opportunities_total = len(opportunities)
    active_opportunities_total = sum(1 for row in opportunities if is_student_visible_opportunity(row))
    expired_opportunities_total = sum(1 for row in opportunities if is_opportunity_expired(row))
    inactive_opportunities_total = sum(
        1 for row in opportunities if (str(row.lifecycle_status or "published").strip().lower() != "published")
    )
    verified_opportunities_total = sum(1 for row in opportunities if (str(row.trust_status or TRUST_STATUS_UNREVIEWED).strip().lower() == TRUST_STATUS_VERIFIED))
    needs_review_opportunities_total = sum(1 for row in opportunities if (str(row.trust_status or TRUST_STATUS_UNREVIEWED).strip().lower() == TRUST_STATUS_NEEDS_REVIEW))
    blocked_opportunities_total = sum(1 for row in opportunities if (str(row.trust_status or TRUST_STATUS_UNREVIEWED).strip().lower() == TRUST_STATUS_BLOCKED))
    social_posts_total = await Post.find_many().count()
    social_comments_total = await SocialComment.find_many().count()
    jobs_dead_count = await BackgroundJob.find_many(BackgroundJob.status == "dead").count()
    return AdminOverviewResponse(
        users_total=users_total,
        active_users=active_users,
        opportunities_total=opportunities_total,
        active_opportunities_total=active_opportunities_total,
        expired_opportunities_total=expired_opportunities_total,
        inactive_opportunities_total=inactive_opportunities_total,
        verified_opportunities_total=verified_opportunities_total,
        needs_review_opportunities_total=needs_review_opportunities_total,
        blocked_opportunities_total=blocked_opportunities_total,
        social_posts_total=social_posts_total,
        social_comments_total=social_comments_total,
        jobs_dead_count=jobs_dead_count,
        generated_at=utc_now(),
    )


@router.get("/opportunities", response_model=list[AdminOpportunityResponse])
async def admin_list_opportunities(
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    page: Optional[int] = Query(default=None, ge=1),
    source: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    quality_min: Optional[float] = Query(default=None, ge=0.0, le=100.0),
    trust_status: Optional[str] = Query(default=None),
    _: User = Depends(get_current_admin_user),
) -> Any:
    computed_skip = skip if page is None else (int(page) - 1) * int(limit)
    filters: dict[str, Any] = {}
    if source:
        filters["source"] = source.strip()
    if status:
        filters["opportunity_status"] = _validate_opportunity_status(status)
    if quality_min is not None:
        filters["quality_score"] = {"$gte": float(quality_min)}
    if trust_status:
        filters["trust_status"] = _validate_trust_status(trust_status)
    query = Opportunity.find_many(filters) if filters else Opportunity.find_many()
    rows = await query.sort("-updated_at").skip(computed_skip).limit(limit).to_list()
    return [_opportunity_payload(row) for row in rows]


@router.post("/opportunities", response_model=AdminOpportunityResponse)
async def admin_create_opportunity(
    payload: AdminOpportunityCreate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    lifecycle_status = _validate_lifecycle_status(payload.lifecycle_status)
    if payload.duration_end < payload.duration_start:
        raise HTTPException(status_code=400, detail="duration_end must be after duration_start")

    normalized_opportunity_type = canonical_opportunity_type(payload.opportunity_type) or "Job"
    normalized_ppo_available = _normalize_ppo_available(payload.ppo_available)
    if normalized_opportunity_type != "Internship":
        normalized_ppo_available = None

    opportunity = Opportunity(
        title=payload.title,
        description=payload.description,
        url=payload.url,
        opportunity_type=normalized_opportunity_type,
        portal_category=resolve_opportunity_portal(
            opportunity_type=payload.opportunity_type,
            title=payload.title,
            description=payload.description,
        ),
        university=payload.university,
        domain=payload.domain,
        source=payload.source,
        location=payload.location,
        eligibility=payload.eligibility,
        ppo_available=normalized_ppo_available,
        duration_start=payload.duration_start,
        duration_end=payload.duration_end,
        deadline=payload.deadline,
        posted_by_user_id=current_user.id,
        updated_at=utc_now(),
        last_seen_at=utc_now(),
    )
    apply_trust_assessment(opportunity, assess_opportunity_trust(opportunity))
    if payload.trust_status:
        opportunity.trust_status = _validate_trust_status(payload.trust_status)
        opportunity.reviewed_by_user_id = current_user.id
        opportunity.reviewed_at = utc_now()
    if payload.verification_evidence:
        opportunity.verification_evidence = list(payload.verification_evidence)
    _apply_lifecycle_status(opportunity, lifecycle_status)
    await opportunity.insert()
    await _audit_admin_action(
        action="opportunity.create",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"opportunity_id": str(opportunity.id), "title": opportunity.title},
    )
    return _opportunity_payload(opportunity)


@router.patch("/opportunities/{opportunity_id}", response_model=AdminOpportunityResponse)
async def admin_update_opportunity(
    opportunity_id: PydanticObjectId,
    payload: AdminOpportunityUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await Opportunity.get(opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    updates = payload.model_dump(exclude_none=True)
    if "lifecycle_status" in updates:
        updates["lifecycle_status"] = _validate_lifecycle_status(str(updates["lifecycle_status"] or ""))
    if "trust_status" in updates:
        updates["trust_status"] = _validate_trust_status(str(updates["trust_status"] or ""))
    if "opportunity_type" in updates:
        updates["opportunity_type"] = canonical_opportunity_type(str(updates["opportunity_type"] or "")) or row.opportunity_type
    if "ppo_available" in updates:
        updates["ppo_available"] = _normalize_ppo_available(updates.get("ppo_available"))
    next_duration_start = updates.get("duration_start", row.duration_start)
    next_duration_end = updates.get("duration_end", row.duration_end)
    if next_duration_start and next_duration_end and next_duration_end < next_duration_start:
        raise HTTPException(status_code=400, detail="duration_end must be after duration_start")

    for field, value in updates.items():
        if field == "lifecycle_status":
            continue
        setattr(row, field, value)
    if (row.opportunity_type or "").strip().lower() != "internship":
        row.ppo_available = None
    row.portal_category = resolve_opportunity_portal(
        opportunity_type=row.opportunity_type,
        title=row.title,
        description=row.description,
        portal_category=row.portal_category,
    )
    computed_assessment = assess_opportunity_trust(row)
    apply_trust_assessment(row, computed_assessment)
    if "trust_status" in updates:
        row.trust_status = str(updates["trust_status"])
        row.reviewed_by_user_id = current_user.id
        row.reviewed_at = utc_now()
    if "verification_evidence" in updates and updates["verification_evidence"] is not None:
        row.verification_evidence = list(updates["verification_evidence"])
    if "lifecycle_status" in updates:
        _apply_lifecycle_status(row, str(updates["lifecycle_status"]))
    row.updated_at = utc_now()
    row.last_seen_at = utc_now()
    await row.save()
    await _audit_admin_action(
        action="opportunity.update",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"opportunity_id": str(row.id), "changed_fields": sorted(list(updates.keys()))},
    )
    return _opportunity_payload(row)


@router.delete("/opportunities/{opportunity_id}", response_model=dict)
async def admin_delete_opportunity(
    opportunity_id: PydanticObjectId,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await Opportunity.get(opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    await row.delete()
    await _audit_admin_action(
        action="opportunity.delete",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"opportunity_id": str(opportunity_id)},
    )
    return {"status": "ok", "opportunity_id": str(opportunity_id)}


@router.patch("/opportunities/{opportunity_id}/status", response_model=AdminOpportunityResponse)
async def admin_update_opportunity_status(
    opportunity_id: PydanticObjectId,
    payload: AdminOpportunityStatusUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await Opportunity.get(opportunity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    row.opportunity_status = _validate_opportunity_status(payload.status)
    if row.opportunity_status in {"filled", "removed", "expired"}:
        row.lifecycle_status = "closed" if row.opportunity_status in {"filled", "expired"} else "paused"
        row.closed_at = utc_now() if row.opportunity_status in {"filled", "expired"} else row.closed_at
    row.lifecycle_updated_at = utc_now()
    row.updated_at = utc_now()
    await row.save()
    await _audit_admin_action(
        action="opportunity.status.update",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"opportunity_id": str(opportunity_id), "status": row.opportunity_status},
    )
    return _opportunity_payload(row)


@router.post("/opportunities/run-quality-pipeline", response_model=dict)
async def admin_run_quality_pipeline(
    payload: AdminQualityPipelineRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    if payload.enqueue:
        job = await job_runner.enqueue(
            job_type="opportunities.quality_pipeline",
            payload={"stale_days": payload.stale_days, "limit": payload.limit},
            max_attempts=2,
            dedupe_key="admin:opportunities.quality_pipeline",
        )
        result = {"status": "queued", "job_id": str(job.id)}
    else:
        from app.services.opportunity_quality_service import opportunity_quality_scorer

        result = await opportunity_quality_scorer.run_quality_pipeline(
            stale_days=payload.stale_days,
            limit=payload.limit,
        )
    await _audit_admin_action(
        action="opportunity.quality_pipeline",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"enqueue": payload.enqueue, **dict(result or {})},
    )
    return result


@router.post("/dedup/run", response_model=dict)
async def admin_run_deduplication(
    payload: AdminDedupRunRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    job_payload = {
        "limit": payload.limit,
        "execute": payload.execute,
        "mark_duplicate_closed": payload.mark_duplicate_closed,
    }
    if payload.enqueue:
        job = await job_runner.enqueue(
            job_type="opportunities.dedup_scan",
            payload=job_payload,
            max_attempts=2,
            dedupe_key=f"admin:opportunities.dedup_scan:{payload.execute}:{payload.mark_duplicate_closed}",
        )
        result = {"status": "queued", "job_id": str(job.id)}
    else:
        from app.services.duplicate_detector import duplicate_detector

        result = await duplicate_detector.scan_existing(**job_payload)
    await _audit_admin_action(
        action="dedup.run",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"enqueue": payload.enqueue, **dict(result or {})},
    )
    return result


@router.get("/social/posts", response_model=list[AdminPostResponse])
async def admin_list_posts(
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await Post.find_many().sort("-created_at").skip(skip).limit(limit).to_list()
    return [
        AdminPostResponse(
            id=str(row.id),
            user_id=str(row.user_id),
            domain=row.domain,
            content=row.content,
            likes_count=int(row.likes_count or 0),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/social/comments", response_model=list[AdminCommentResponse])
async def admin_list_comments(
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await SocialComment.find_many().sort("-created_at").skip(skip).limit(limit).to_list()
    return [
        AdminCommentResponse(
            id=str(row.id),
            post_id=str(row.post_id),
            user_id=str(row.user_id),
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete("/social/posts/{post_id}", response_model=dict)
async def admin_delete_post(
    post_id: PydanticObjectId,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    post = await Post.get(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    await SocialComment.find_many(SocialComment.post_id == post_id).delete()
    await post.delete()
    await _audit_admin_action(
        action="social.post.delete",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"post_id": str(post_id)},
    )
    return {"status": "ok", "post_id": str(post_id)}


@router.delete("/social/comments/{comment_id}", response_model=dict)
async def admin_delete_comment(
    comment_id: PydanticObjectId,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await SocialComment.get(comment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    await row.delete()
    await _audit_admin_action(
        action="social.comment.delete",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"comment_id": str(comment_id)},
    )
    return {"status": "ok", "comment_id": str(comment_id)}


@router.get("/users", response_model=list[AdminUserResponse])
async def admin_list_users(
    limit: int = Query(default=120, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await User.find_many().sort("-created_at").skip(skip).limit(limit).to_list()
    return [_admin_user_payload(row) for row in rows]


@router.get("/users/{user_id}", response_model=dict)
async def admin_get_user_detail(
    user_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    row = await User.get(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    since = utc_now() - timedelta(days=30)
    interactions = await OpportunityInteraction.find_many(
        OpportunityInteraction.user_id == user_id,
        OpportunityInteraction.created_at >= since,
    ).to_list()
    by_type: dict[str, int] = {}
    for item in interactions:
        event_type = str(item.event_type or item.interaction_type or "unknown")
        by_type[event_type] = by_type.get(event_type, 0) + 1
    payload = _admin_user_payload(row).model_dump(mode="json")
    payload["interaction_summary_30d"] = {
        "total": len(interactions),
        "by_type": by_type,
    }
    return payload


@router.patch("/users/{user_id}/status", response_model=AdminUserResponse)
async def admin_update_user_status(
    user_id: PydanticObjectId,
    payload: AdminUserStatusUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await User.get(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if bool(row.is_admin):
        raise HTTPException(status_code=400, detail="Admin identity status cannot be modified here")
    row.is_active = bool(payload.is_active)
    await row.save()
    await _audit_admin_action(
        action="user.status.update",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"target_user_id": str(user_id), "is_active": bool(payload.is_active)},
    )
    return _admin_user_payload(row)


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
async def admin_update_user_role(
    user_id: PydanticObjectId,
    payload: AdminUserRoleUpdate,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await User.get(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if str(row.id) == str(current_user.id) and payload.is_admin is False:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin access")
    changes: dict[str, Any] = {}
    if payload.account_type is not None and row.account_type != payload.account_type:
        row.account_type = payload.account_type
        changes["account_type"] = payload.account_type
    if payload.is_admin is not None and bool(row.is_admin) != bool(payload.is_admin):
        row.is_admin = bool(payload.is_admin)
        changes["is_admin"] = bool(payload.is_admin)
    if changes:
        await row.save()
    await _audit_admin_action(
        action="user.role.update",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"target_user_id": str(user_id), "changes": changes},
    )
    return _admin_user_payload(row)


@router.delete("/users/{user_id}", response_model=dict)
async def admin_soft_delete_user(
    user_id: PydanticObjectId,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    row = await User.get(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if bool(row.is_admin):
        raise HTTPException(status_code=400, detail="Admin identities cannot be deleted here")
    row.email = f"deleted-{str(row.id)}@deleted.local"
    row.full_name = None
    row.username = None
    row.hashed_password = "DELETED_USER"
    row.auth_provider = "deleted"
    row.is_active = False
    row.profile_embedding = []
    await row.save()
    await _audit_admin_action(
        action="user.soft_delete",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"target_user_id": str(user_id)},
    )
    return {"status": "ok", "user_id": str(user_id)}


@router.get("/jobs/recent", response_model=list[dict[str, Any]])
async def admin_recent_jobs(
    limit: int = Query(default=40, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await BackgroundJob.find_many().sort("-created_at").limit(limit).to_list()
    return [
        {
            "id": str(row.id),
            "job_type": row.job_type,
            "status": row.status,
            "attempts": int(row.attempts or 0),
            "max_attempts": int(row.max_attempts or 0),
            "run_after": row.run_after.isoformat() if row.run_after else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "last_error": row.last_error,
            "result": row.result,
        }
        for row in rows
    ]


@router.post("/jobs/enqueue", response_model=dict)
async def admin_enqueue_job(
    payload: AdminJobEnqueueRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    job = await job_runner.enqueue(
        job_type=payload.job_type.strip(),
        payload=payload.payload or {},
        max_attempts=int(payload.max_attempts),
        dedupe_key=payload.dedupe_key,
    )
    await _audit_admin_action(
        action="job.enqueue",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"job_id": str(job.id), "job_type": payload.job_type.strip()},
    )
    return {"status": "ok", "job_id": str(job.id)}


@router.post("/jobs/{job_name}/trigger", response_model=dict)
async def admin_trigger_named_job(
    job_name: str,
    payload: dict[str, Any],
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    normalized = job_name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="job_name is required")
    job = await job_runner.enqueue(
        job_type=normalized,
        payload=payload or {},
        max_attempts=2,
        dedupe_key=f"admin:{normalized}:{utc_now().date().isoformat()}",
    )
    await _audit_admin_action(
        action="job.trigger",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"job_name": normalized, "job_id": str(job.id)},
    )
    return {"status": "queued", "job_id": str(job.id), "job_name": normalized}


@router.get("/jobs/{job_name}/status", response_model=dict)
async def admin_named_job_status(
    job_name: str,
    _: User = Depends(get_current_admin_user),
) -> Any:
    normalized = job_name.strip()
    rows = await BackgroundJob.find_many(BackgroundJob.job_type == normalized).sort("-created_at").limit(5).to_list()
    return {
        "job_name": normalized,
        "recent": [
            {
                "id": str(row.id),
                "status": row.status,
                "attempts": int(row.attempts or 0),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "last_error": row.last_error,
                "result": row.result,
            }
            for row in rows
        ],
    }


@router.get("/jobs/history", response_model=list[dict[str, Any]])
async def admin_jobs_history(
    job: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(get_current_admin_user),
) -> Any:
    filters: dict[str, Any] = {}
    if job:
        filters["job_type"] = job.strip()
    if status:
        filters["status"] = status.strip().lower()
    rows = await (BackgroundJob.find_many(filters) if filters else BackgroundJob.find_many()).sort("-created_at").limit(limit).to_list()
    return [
        {
            "id": str(row.id),
            "job_type": row.job_type,
            "status": row.status,
            "attempts": int(row.attempts or 0),
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "last_error": row.last_error,
            "result": row.result,
        }
        for row in rows
    ]


@router.post("/scrapers/{source}/trigger", response_model=dict)
async def admin_trigger_scraper(
    source: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source_key = source.strip().lower() or "all"
    job = await job_runner.enqueue(
        job_type="scraper.run",
        payload={"requested_source": source_key, "triggered_by": "admin"},
        max_attempts=2,
        dedupe_key=f"admin:scraper.run:{source_key}",
    )
    await _audit_admin_action(
        action="scraper.trigger",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"source": source_key, "job_id": str(job.id)},
    )
    return {"status": "queued", "source": source_key, "job_id": str(job.id)}


@router.post("/scrapers/{source}/pause", response_model=dict)
async def admin_pause_scraper(
    source: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source_key = source.strip().lower()
    row = await ScraperRegistration.find_one(
        {
            "$or": [
                {"scraper_key": source_key},
                {"source_name": source_key},
                {"domain": source_key},
            ]
        }
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scraper registration not found")
    row.status = ScraperRegistrationStatus.paused
    row.updated_at = utc_now()
    await row.save()
    await _audit_admin_action(
        action="scraper.pause",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"source": source_key, "registration_id": str(row.id)},
    )
    return {"status": "paused", "source": source_key, "registration_id": str(row.id)}


@router.get("/scrapers/runs", response_model=list[dict[str, Any]])
async def admin_scraper_runs(
    source: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: User = Depends(get_current_admin_user),
) -> Any:
    filters: dict[str, Any] = {}
    if source:
        filters["source_name"] = source.strip()
    if status:
        filters["status"] = status.strip().lower()
    rows = await (ScraperRunLog.find_many(filters) if filters else ScraperRunLog.find_many()).sort("-run_end").limit(limit).to_list()
    return [
        {
            "id": str(row.id),
            "source_name": row.source_name,
            "status": row.status,
            "run_start": row.run_start.isoformat(),
            "run_end": row.run_end.isoformat(),
            "items_fetched": int(row.items_fetched or 0),
            "items_inserted": int(row.items_inserted or 0),
            "items_deduplicated": int(row.items_deduplicated or 0),
            "parse_error_count": int(row.parse_error_count or 0),
            "silent_failure": bool(row.silent_failure),
            "avg_trust_score": row.avg_trust_score,
        }
        for row in rows
    ]


@router.post("/ranker/train", response_model=dict)
async def admin_train_ranker(
    payload: AdminTrainRankerRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    job_payload = {
        "lookback_days": payload.lookback_days,
        "min_rows": payload.min_rows,
        "auto_activate": payload.auto_activate,
        "notes": "admin_triggered",
    }
    if payload.enqueue:
        job = await job_runner.enqueue(
            job_type="mlops.retrain",
            payload=job_payload,
            max_attempts=1,
            dedupe_key="admin:mlops.retrain",
        )
        result = {"status": "queued", "job_id": str(job.id)}
    else:
        from app.services.mlops.retraining_service import retraining_service

        result_obj = await retraining_service.retrain_and_register(**job_payload)
        result = {
            "status": "completed",
            "model_version_id": result_obj.model_version_id,
            "auto_activated": bool(result_obj.auto_activated),
            "metrics": result_obj.metrics,
        }
    await _audit_admin_action(
        action="ranker.train",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"enqueue": payload.enqueue, **dict(result or {})},
    )
    return result


@router.get("/ranker/versions", response_model=list[dict[str, Any]])
async def admin_ranker_versions(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await RankingModelVersion.find_many().sort("-created_at").limit(limit).to_list()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "is_active": bool(row.is_active),
            "metrics": row.metrics,
            "training_rows": int(row.training_rows or 0),
            "serving_ready": bool(row.serving_ready),
            "artifact_uri": row.artifact_uri,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/ranker/activate/{version}", response_model=dict)
async def admin_activate_ranker_version(
    version: str,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    try:
        model = await ranking_model_service.activate(model_id=version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _audit_admin_action(
        action="ranker.activate",
        actor=current_user,
        success=True,
        request=request,
        reason_payload={"model_version_id": str(model.id), "name": model.name},
    )
    return {"status": "ok", "model_version_id": str(model.id), "name": model.name}


@router.get("/analytics/overview", response_model=dict)
async def admin_analytics_overview(_: User = Depends(get_current_admin_user)) -> Any:
    now = utc_now()
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)
    interactions_7d = await OpportunityInteraction.find_many(OpportunityInteraction.created_at >= since_7d).to_list()
    interactions_30d = await OpportunityInteraction.find_many(OpportunityInteraction.created_at >= since_30d).to_list()
    applications_30d = await Application.find_many(Application.created_at >= since_30d).count()

    def _rates(rows: list[OpportunityInteraction]) -> dict[str, float | int]:
        impressions = sum(1 for row in rows if str(row.event_type or row.interaction_type) == "impression")
        clicks = sum(1 for row in rows if str(row.event_type or row.interaction_type) == "click")
        applies = sum(1 for row in rows if str(row.event_type or row.interaction_type) in {"apply_start", "apply_complete"})
        return {
            "interactions": len(rows),
            "impressions": impressions,
            "clicks": clicks,
            "applies": applies,
            "ctr": round(clicks / max(1, impressions), 6),
            "apply_rate": round(applies / max(1, impressions), 6),
        }

    return {
        "generated_at": now.isoformat(),
        "users_total": int(await User.find_many().count()),
        "opportunities_total": int(await Opportunity.find_many().count()),
        "applications_30d": int(applications_30d),
        "last_7d": _rates(interactions_7d),
        "last_30d": _rates(interactions_30d),
    }


@router.get("/analytics/sources", response_model=list[dict[str, Any]])
async def admin_analytics_sources(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
) -> Any:
    opportunities = await Opportunity.find_many().limit(20_000).to_list()
    by_source: dict[str, dict[str, Any]] = {}
    for row in opportunities:
        source = str(row.source or "unknown").strip().lower() or "unknown"
        bucket = by_source.setdefault(source, {"source": source, "opportunities": 0, "quality_sum": 0.0, "quality_count": 0})
        bucket["opportunities"] += 1
        if row.quality_score is not None:
            bucket["quality_sum"] += float(row.quality_score)
            bucket["quality_count"] += 1
    rows = []
    for bucket in by_source.values():
        rows.append(
            {
                "source": bucket["source"],
                "opportunities": int(bucket["opportunities"]),
                "avg_quality_score": round(bucket["quality_sum"] / max(1, bucket["quality_count"]), 3),
            }
        )
    rows.sort(key=lambda item: item["opportunities"], reverse=True)
    return rows[:limit]


@router.get("/analytics/ranking", response_model=list[dict[str, Any]])
async def admin_analytics_ranking(
    days: int = Query(default=30, ge=1, le=365),
    _: User = Depends(get_current_admin_user),
) -> Any:
    since = utc_now() - timedelta(days=days)
    rows = await OpportunityInteraction.find_many(OpportunityInteraction.created_at >= since).to_list()
    by_mode: dict[str, dict[str, int]] = {}
    for row in rows:
        mode = str(row.ranking_mode or "unknown").strip().lower() or "unknown"
        event_type = str(row.event_type or row.interaction_type or "unknown")
        bucket = by_mode.setdefault(mode, {"impressions": 0, "clicks": 0, "saves": 0, "applies": 0})
        if event_type == "impression":
            bucket["impressions"] += 1
        elif event_type == "click":
            bucket["clicks"] += 1
        elif event_type == "save":
            bucket["saves"] += 1
        elif event_type in {"apply_start", "apply_complete"}:
            bucket["applies"] += 1
    payload = []
    for mode, bucket in by_mode.items():
        impressions = max(1, bucket["impressions"])
        payload.append(
            {
                "ranking_mode": mode,
                **bucket,
                "ctr": round(bucket["clicks"] / impressions, 6),
                "save_rate": round(bucket["saves"] / impressions, 6),
                "apply_rate": round(bucket["applies"] / impressions, 6),
            }
        )
    payload.sort(key=lambda item: item["impressions"], reverse=True)
    return payload


@router.get("/audit-events", response_model=list[dict[str, Any]])
async def admin_audit_events(
    limit: int = Query(default=200, ge=1, le=1000),
    event_type: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    user_id: Optional[PydanticObjectId] = Query(default=None),
    success: Optional[bool] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    _: User = Depends(get_current_admin_user),
) -> Any:
    filters: dict[str, Any] = {
        "$or": [
            {"event_type": {"$regex": "^admin\\."}},
            {"event_type": "login.admin"},
        ]
    }
    if event_type:
        filters["event_type"] = event_type.strip().lower()
        filters.pop("$or", None)
    if email:
        filters["email"] = email.strip().lower()
    if user_id is not None:
        filters["user_id"] = user_id
    if success is not None:
        filters["success"] = bool(success)
    if date_from is not None or date_to is not None:
        created_filter: dict[str, datetime] = {}
        if date_from is not None:
            created_filter["$gte"] = date_from
        if date_to is not None:
            created_filter["$lte"] = date_to
        filters["created_at"] = created_filter
    rows = (
        await AuthAuditEvent.find_many(filters)
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    payload: list[dict[str, Any]] = []
    for row in rows:
        payload.append(
            {
                "id": str(row.id),
                "event_type": row.event_type,
                "email": row.email,
                "account_type": row.account_type,
                "purpose": row.purpose,
                "success": bool(row.success),
                "reason": row.reason,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "user_id": str(row.user_id) if row.user_id else None,
                "lock_applied": bool(row.lock_applied),
                "lock_until": row.lock_until.isoformat() if row.lock_until else None,
                "created_at": row.created_at.isoformat(),
            }
        )
    return payload
