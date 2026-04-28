from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import get_current_admin_user
from app.models.auth_audit_event import AuthAuditEvent
from app.models.background_job import BackgroundJob
from app.models.opportunity import Opportunity
from app.models.post import Comment as SocialComment
from app.models.post import Post
from app.models.user import User
from app.core.time import utc_now
from app.services.auth_security_service import auth_security_service
from app.services.job_runner import job_runner
from app.services.opportunity_visibility import (
    canonical_opportunity_type,
    is_opportunity_expired,
    is_student_visible_opportunity,
    resolve_opportunity_portal,
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
    eligibility: Optional[str] = None
    ppo_available: Optional[str] = None
    duration_start: datetime
    duration_end: datetime
    deadline: datetime
    lifecycle_status: str = "published"


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
    lifecycle_status: str
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


class AdminJobEnqueueRequest(BaseModel):
    job_type: str = Field(min_length=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1, le=50)
    dedupe_key: Optional[str] = None


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
        eligibility=row.eligibility,
        ppo_available=row.ppo_available,
        lifecycle_status=row.lifecycle_status or "published",
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
        social_posts_total=social_posts_total,
        social_comments_total=social_comments_total,
        jobs_dead_count=jobs_dead_count,
        generated_at=utc_now(),
    )


@router.get("/opportunities", response_model=list[AdminOpportunityResponse])
async def admin_list_opportunities(
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await Opportunity.find_many().sort("-updated_at").skip(skip).limit(limit).to_list()
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
    return [
        AdminUserResponse(
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
        for row in rows
    ]


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


@router.get("/audit-events", response_model=list[dict[str, Any]])
async def admin_audit_events(
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = (
        await AuthAuditEvent.find_many(
            {
                "$or": [
                    {"event_type": {"$regex": "^admin\\."}},
                    {"event_type": "login.admin"},
                ]
            }
        )
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
