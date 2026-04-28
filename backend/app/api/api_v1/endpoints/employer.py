from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from beanie import PydanticObjectId
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_current_employer_user
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.recruiter_audit_log import RecruiterAuditLog
from app.models.user import User
from app.services.opportunity_visibility import canonical_opportunity_type, resolve_opportunity_portal
from app.core.time import utc_now

router = APIRouter()

LIFECYCLE_STATES: set[str] = {"draft", "published", "paused", "closed"}
PIPELINE_STATES: set[str] = {"applied", "shortlisted", "rejected", "interview"}


class EmployerOpportunityCreate(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    description: str = Field(min_length=20, max_length=8000)
    application_url: str = Field(min_length=8, max_length=1200)
    opportunity_type: str = Field(default="Job", min_length=2, max_length=80)
    domain: Optional[str] = Field(default=None, max_length=160)
    deadline: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)
    eligibility: Optional[str] = Field(default=None, max_length=600)
    lifecycle_status: Literal["draft", "published", "paused", "closed"] = "draft"


class EmployerOpportunityUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=220)
    description: Optional[str] = Field(default=None, min_length=20, max_length=8000)
    application_url: Optional[str] = Field(default=None, min_length=8, max_length=1200)
    opportunity_type: Optional[str] = Field(default=None, min_length=2, max_length=80)
    domain: Optional[str] = Field(default=None, max_length=160)
    deadline: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)
    eligibility: Optional[str] = Field(default=None, max_length=600)


class LifecycleUpdateRequest(BaseModel):
    status: Literal["draft", "published", "paused", "closed"]


class PipelineStateUpdateRequest(BaseModel):
    pipeline_state: Literal["applied", "shortlisted", "rejected", "interview"]
    notes: Optional[str] = Field(default=None, max_length=1000)


class EmployerOpportunityResponse(BaseModel):
    id: str
    title: str
    description: str
    application_url: str
    opportunity_type: Optional[str] = None
    domain: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    eligibility: Optional[str] = None
    deadline: Optional[datetime] = None
    lifecycle_status: str
    published_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    applications_count: int = 0


class EmployerApplicationResponse(BaseModel):
    application_id: str
    opportunity_id: str
    opportunity_title: str
    applicant_user_id: str
    applicant_name: Optional[str] = None
    applicant_email: Optional[str] = None
    status: str
    pipeline_state: str
    pipeline_notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime
    pipeline_updated_at: Optional[datetime] = None


class RecruiterAuditLogResponse(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    application_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EmployerDashboardSummary(BaseModel):
    company_name: Optional[str] = None
    opportunities_posted: int
    active_opportunities: int
    total_applications: int
    submitted_applications: int
    pending_applications: int
    auto_filled_applications: int
    shortlisted_applications: int
    rejected_applications: int
    interview_applications: int
    recent_applications: list[EmployerApplicationResponse]


class EmployerApplicationsListResponse(BaseModel):
    total: int
    rows: list[EmployerApplicationResponse]


def _normalize_company_name(*, profile: Optional[Profile], user: User) -> str:
    candidate = (profile.company_name if profile else None) or user.full_name or "Employer Organization"
    text = str(candidate).strip()
    return text or "Employer Organization"


def _normalize_lifecycle_status(status: Optional[str], *, default: str = "draft") -> str:
    value = (status or default).strip().lower()
    if value not in LIFECYCLE_STATES:
        raise HTTPException(status_code=400, detail=f"lifecycle_status must be one of: {', '.join(sorted(LIFECYCLE_STATES))}")
    return value


def _normalize_pipeline_state(state: Optional[str], *, default: str = "applied") -> str:
    value = (state or default).strip().lower()
    if value not in PIPELINE_STATES:
        raise HTTPException(status_code=400, detail=f"pipeline_state must be one of: {', '.join(sorted(PIPELINE_STATES))}")
    return value


def _coerce_pipeline_state(state: Optional[str], *, default: str = "applied") -> str:
    value = (state or default).strip().lower()
    if value not in PIPELINE_STATES:
        return default
    return value


def _opportunity_to_response(*, opportunity: Opportunity, applications_count: int) -> EmployerOpportunityResponse:
    return EmployerOpportunityResponse(
        id=str(opportunity.id),
        title=opportunity.title,
        description=opportunity.description,
        application_url=opportunity.url,
        opportunity_type=opportunity.opportunity_type,
        domain=opportunity.domain,
        company_name=opportunity.university,
        location=opportunity.location,
        eligibility=opportunity.eligibility,
        deadline=opportunity.deadline,
        lifecycle_status=(opportunity.lifecycle_status or "published"),
        published_at=opportunity.published_at,
        paused_at=opportunity.paused_at,
        closed_at=opportunity.closed_at,
        created_at=opportunity.created_at,
        applications_count=int(applications_count),
    )


async def _load_employer_opportunities(user_id: PydanticObjectId) -> list[Opportunity]:
    return await Opportunity.find_many(Opportunity.posted_by_user_id == user_id).sort("-created_at").to_list()


async def _load_applications_for_opportunities(opportunity_ids: list[PydanticObjectId]) -> list[Application]:
    if not opportunity_ids:
        return []
    return await Application.find_many(In(Application.opportunity_id, opportunity_ids)).sort("-created_at").to_list()


async def _audit(
    *,
    recruiter_user_id: PydanticObjectId,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    opportunity_id: Optional[PydanticObjectId] = None,
    application_id: Optional[PydanticObjectId] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    event = RecruiterAuditLog(
        recruiter_user_id=recruiter_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=(entity_id or None),
        opportunity_id=opportunity_id,
        application_id=application_id,
        metadata=dict(metadata or {}),
        created_at=utc_now(),
    )
    await event.insert()


def _lifecycle_transition_allowed(*, current: str, target: str) -> bool:
    if current == target:
        return True
    allowed: dict[str, set[str]] = {
        "draft": {"published", "closed"},
        "published": {"paused", "closed"},
        "paused": {"published", "closed"},
        "closed": set(),
    }
    return target in allowed.get(current, set())


def _serialize_application_row(*, application: Application, opportunity: Opportunity, user_map: dict[str, User]) -> EmployerApplicationResponse:
    applicant = user_map.get(str(application.user_id))
    return EmployerApplicationResponse(
        application_id=str(application.id),
        opportunity_id=str(opportunity.id),
        opportunity_title=opportunity.title,
        applicant_user_id=str(application.user_id),
        applicant_name=applicant.full_name if applicant else None,
        applicant_email=applicant.email if applicant else None,
        status=application.status,
        pipeline_state=_coerce_pipeline_state(application.pipeline_state, default="applied"),
        pipeline_notes=application.pipeline_notes,
        submitted_at=application.submitted_at,
        created_at=application.created_at,
        pipeline_updated_at=application.pipeline_updated_at,
    )


def _csv_response(*, filename: str, rows: list[dict[str, Any]]) -> Response:
    if not rows:
        body = ""
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/opportunities", response_model=EmployerOpportunityResponse)
async def create_employer_opportunity(
    payload: EmployerOpportunityCreate,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    company_name = _normalize_company_name(profile=profile, user=current_user)

    cleaned_url = str(payload.application_url or "").strip()
    if not cleaned_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="application_url must start with http:// or https://")

    existing_url = await Opportunity.find_one(Opportunity.url == cleaned_url)
    if existing_url:
        raise HTTPException(status_code=400, detail="An opportunity with this application_url already exists")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lifecycle_status = _normalize_lifecycle_status(payload.lifecycle_status, default="draft")

    opportunity = Opportunity(
        title=payload.title.strip(),
        description=payload.description.strip(),
        url=cleaned_url,
        opportunity_type=canonical_opportunity_type(payload.opportunity_type) or "Job",
        portal_category=resolve_opportunity_portal(
            opportunity_type=payload.opportunity_type,
            title=payload.title,
            description=payload.description,
        ),
        domain=(payload.domain or "").strip() or None,
        university=company_name,
        source="employer_portal",
        location=(payload.location or "").strip() or None,
        eligibility=(payload.eligibility or "").strip() or None,
        deadline=payload.deadline,
        is_employer_post=True,
        posted_by_user_id=current_user.id,
        lifecycle_status=lifecycle_status,
        published_at=now if lifecycle_status == "published" else None,
        paused_at=now if lifecycle_status == "paused" else None,
        closed_at=now if lifecycle_status == "closed" else None,
        lifecycle_updated_at=now,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    await opportunity.insert()

    await _audit(
        recruiter_user_id=current_user.id,
        action="opportunity.create",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        opportunity_id=opportunity.id,
        metadata={"lifecycle_status": lifecycle_status, "title": opportunity.title},
    )
    return _opportunity_to_response(opportunity=opportunity, applications_count=0)


@router.get("/opportunities", response_model=list[EmployerOpportunityResponse])
async def list_employer_opportunities(
    status: Optional[str] = None,
    search: Optional[str] = None,
    domain: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    opportunities = await _load_employer_opportunities(current_user.id)

    normalized_status = _normalize_lifecycle_status(status, default="published") if status else None
    normalized_search = (search or "").strip().lower()
    normalized_domain = (domain or "").strip().lower()

    filtered: list[Opportunity] = []
    for item in opportunities:
        if normalized_status and (item.lifecycle_status or "published") != normalized_status:
            continue
        if normalized_domain and (item.domain or "").strip().lower() != normalized_domain:
            continue
        if normalized_search:
            haystack = " ".join(
                [
                    item.title or "",
                    item.description or "",
                    item.opportunity_type or "",
                    item.domain or "",
                    item.location or "",
                ]
            ).lower()
            if normalized_search not in haystack:
                continue
        filtered.append(item)

    safe_skip = max(0, skip)
    safe_limit = max(1, min(limit, 500))
    paged = filtered[safe_skip : safe_skip + safe_limit]

    opportunity_ids = [item.id for item in paged]
    applications = await _load_applications_for_opportunities(opportunity_ids)

    counts: dict[str, int] = {}
    for app in applications:
        key = str(app.opportunity_id)
        counts[key] = counts.get(key, 0) + 1

    return [_opportunity_to_response(opportunity=item, applications_count=counts.get(str(item.id), 0)) for item in paged]


@router.get("/opportunities/export.csv")
async def export_employer_opportunities_csv(
    status: Optional[str] = None,
    search: Optional[str] = None,
    domain: Optional[str] = None,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    rows = await list_employer_opportunities(
        status=status,
        search=search,
        domain=domain,
        skip=0,
        limit=5000,
        current_user=current_user,
    )
    csv_rows = [
        {
            "id": row.id,
            "title": row.title,
            "type": row.opportunity_type or "",
            "domain": row.domain or "",
            "location": row.location or "",
            "deadline": row.deadline.isoformat() if row.deadline else "",
            "lifecycle_status": row.lifecycle_status,
            "applications_count": row.applications_count,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    await _audit(
        recruiter_user_id=current_user.id,
        action="opportunity.export",
        entity_type="opportunity",
        metadata={"row_count": len(csv_rows)},
    )
    return _csv_response(filename="employer_opportunities.csv", rows=csv_rows)


@router.patch("/opportunities/{opportunity_id}", response_model=EmployerOpportunityResponse)
async def update_employer_opportunity(
    opportunity_id: str,
    payload: EmployerOpportunityUpdate,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    try:
        opp_object_id = PydanticObjectId(opportunity_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid opportunity_id")

    opportunity = await Opportunity.get(opp_object_id)
    if not opportunity or opportunity.posted_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Employer opportunity not found")

    updated_fields: dict[str, Any] = {}

    if payload.title is not None:
        opportunity.title = payload.title.strip()
        updated_fields["title"] = opportunity.title
    if payload.description is not None:
        opportunity.description = payload.description.strip()
        updated_fields["description"] = "updated"
    if payload.application_url is not None:
        cleaned_url = payload.application_url.strip()
        if not cleaned_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="application_url must start with http:// or https://")
        existing_url = await Opportunity.find_one(Opportunity.url == cleaned_url, Opportunity.id != opportunity.id)
        if existing_url:
            raise HTTPException(status_code=400, detail="An opportunity with this application_url already exists")
        opportunity.url = cleaned_url
        updated_fields["application_url"] = cleaned_url
    if payload.opportunity_type is not None:
        opportunity.opportunity_type = canonical_opportunity_type(payload.opportunity_type) or opportunity.opportunity_type
        updated_fields["opportunity_type"] = opportunity.opportunity_type
    if payload.domain is not None:
        opportunity.domain = payload.domain.strip() or None
        updated_fields["domain"] = opportunity.domain
    if payload.location is not None:
        opportunity.location = payload.location.strip() or None
        updated_fields["location"] = opportunity.location
    if payload.eligibility is not None:
        opportunity.eligibility = payload.eligibility.strip() or None
        updated_fields["eligibility"] = bool(opportunity.eligibility)

    if payload.deadline is not None:
        opportunity.deadline = payload.deadline
        updated_fields["deadline"] = payload.deadline.isoformat() if payload.deadline else None

    opportunity.portal_category = resolve_opportunity_portal(
        opportunity_type=opportunity.opportunity_type,
        title=opportunity.title,
        description=opportunity.description,
        portal_category=opportunity.portal_category,
    )

    opportunity.updated_at = utc_now()
    opportunity.last_seen_at = opportunity.updated_at
    await opportunity.save()

    if updated_fields:
        await _audit(
            recruiter_user_id=current_user.id,
            action="opportunity.update",
            entity_type="opportunity",
            entity_id=str(opportunity.id),
            opportunity_id=opportunity.id,
            metadata={"updated_fields": updated_fields},
        )

    applications_count = await Application.find_many(Application.opportunity_id == opportunity.id).count()
    return _opportunity_to_response(opportunity=opportunity, applications_count=applications_count)


@router.post("/opportunities/{opportunity_id}/lifecycle", response_model=EmployerOpportunityResponse)
async def update_opportunity_lifecycle(
    opportunity_id: str,
    payload: LifecycleUpdateRequest,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    try:
        opp_object_id = PydanticObjectId(opportunity_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid opportunity_id")

    opportunity = await Opportunity.get(opp_object_id)
    if not opportunity or opportunity.posted_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Employer opportunity not found")

    target = _normalize_lifecycle_status(payload.status)
    current = _normalize_lifecycle_status(opportunity.lifecycle_status, default="published")
    if not _lifecycle_transition_allowed(current=current, target=target):
        raise HTTPException(status_code=400, detail=f"Invalid lifecycle transition: {current} -> {target}")

    now = utc_now()
    opportunity.lifecycle_status = target
    opportunity.lifecycle_updated_at = now
    opportunity.updated_at = now
    opportunity.last_seen_at = now
    if target == "published":
        opportunity.published_at = now
    elif target == "paused":
        opportunity.paused_at = now
    elif target == "closed":
        opportunity.closed_at = now
    await opportunity.save()

    await _audit(
        recruiter_user_id=current_user.id,
        action="opportunity.lifecycle",
        entity_type="opportunity",
        entity_id=str(opportunity.id),
        opportunity_id=opportunity.id,
        metadata={"from": current, "to": target},
    )

    applications_count = await Application.find_many(Application.opportunity_id == opportunity.id).count()
    return _opportunity_to_response(opportunity=opportunity, applications_count=applications_count)


@router.get("/opportunities/{opportunity_id}/applications", response_model=EmployerApplicationsListResponse)
async def list_employer_opportunity_applications(
    opportunity_id: str,
    pipeline_state: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    try:
        opp_object_id = PydanticObjectId(opportunity_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid opportunity_id")

    opportunity = await Opportunity.get(opp_object_id)
    if not opportunity or opportunity.posted_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Employer opportunity not found")

    applications = await Application.find_many(Application.opportunity_id == opportunity.id).sort("-created_at").to_list()
    user_ids = list({application.user_id for application in applications})
    users = await User.find_many(In(User.id, user_ids)).to_list() if user_ids else []
    user_map = {str(user.id): user for user in users}

    normalized_pipeline = _normalize_pipeline_state(pipeline_state, default="applied") if pipeline_state else None
    normalized_search = (search or "").strip().lower()

    filtered_rows: list[EmployerApplicationResponse] = []
    for application in applications:
        row = _serialize_application_row(application=application, opportunity=opportunity, user_map=user_map)
        if normalized_pipeline and row.pipeline_state != normalized_pipeline:
            continue
        if normalized_search:
            haystack = " ".join([row.opportunity_title, row.applicant_name or "", row.applicant_email or "", row.status]).lower()
            if normalized_search not in haystack:
                continue
        filtered_rows.append(row)

    safe_skip = max(0, skip)
    safe_limit = max(1, min(limit, 2000))
    paged = filtered_rows[safe_skip : safe_skip + safe_limit]
    return EmployerApplicationsListResponse(total=len(filtered_rows), rows=paged)


@router.get("/applications", response_model=EmployerApplicationsListResponse)
async def list_all_employer_applications(
    pipeline_state: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    opportunities = await _load_employer_opportunities(current_user.id)
    opportunity_map = {str(item.id): item for item in opportunities}
    opportunity_ids = [item.id for item in opportunities]
    if not opportunity_ids:
        return EmployerApplicationsListResponse(total=0, rows=[])

    applications = await _load_applications_for_opportunities(opportunity_ids)
    user_ids = list({application.user_id for application in applications})
    users = await User.find_many(In(User.id, user_ids)).to_list() if user_ids else []
    user_map = {str(user.id): user for user in users}

    normalized_pipeline = _normalize_pipeline_state(pipeline_state, default="applied") if pipeline_state else None
    normalized_search = (search or "").strip().lower()

    filtered_rows: list[EmployerApplicationResponse] = []
    for application in applications:
        opportunity = opportunity_map.get(str(application.opportunity_id))
        if not opportunity:
            continue
        row = _serialize_application_row(application=application, opportunity=opportunity, user_map=user_map)
        if normalized_pipeline and row.pipeline_state != normalized_pipeline:
            continue
        if normalized_search:
            haystack = " ".join([row.opportunity_title, row.applicant_name or "", row.applicant_email or "", row.status]).lower()
            if normalized_search not in haystack:
                continue
        filtered_rows.append(row)

    safe_skip = max(0, skip)
    safe_limit = max(1, min(limit, 2000))
    paged = filtered_rows[safe_skip : safe_skip + safe_limit]
    return EmployerApplicationsListResponse(total=len(filtered_rows), rows=paged)


@router.get("/applications/export.csv")
async def export_all_employer_applications_csv(
    pipeline_state: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    payload = await list_all_employer_applications(
        pipeline_state=pipeline_state,
        search=search,
        skip=0,
        limit=5000,
        current_user=current_user,
    )
    rows = [
        {
            "application_id": row.application_id,
            "opportunity_id": row.opportunity_id,
            "opportunity_title": row.opportunity_title,
            "applicant_name": row.applicant_name or "",
            "applicant_email": row.applicant_email or "",
            "status": row.status,
            "pipeline_state": row.pipeline_state,
            "pipeline_notes": row.pipeline_notes or "",
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else "",
            "created_at": row.created_at.isoformat(),
            "pipeline_updated_at": row.pipeline_updated_at.isoformat() if row.pipeline_updated_at else "",
        }
        for row in payload.rows
    ]
    await _audit(
        recruiter_user_id=current_user.id,
        action="application.export",
        entity_type="application",
        metadata={"row_count": len(rows)},
    )
    return _csv_response(filename="employer_applications.csv", rows=rows)


@router.patch("/applications/{application_id}/pipeline", response_model=EmployerApplicationResponse)
async def update_application_pipeline_state(
    application_id: str,
    payload: PipelineStateUpdateRequest,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    try:
        app_object_id = PydanticObjectId(application_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application_id")

    application = await Application.get(app_object_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    opportunity = await Opportunity.get(application.opportunity_id)
    if not opportunity or opportunity.posted_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Application not found for this employer")

    target_state = _normalize_pipeline_state(payload.pipeline_state)
    old_state = _normalize_pipeline_state(application.pipeline_state, default="applied")
    application.pipeline_state = target_state
    application.pipeline_notes = (payload.notes or "").strip() or None
    application.pipeline_updated_at = utc_now()
    application.pipeline_updated_by = current_user.id
    await application.save()

    await _audit(
        recruiter_user_id=current_user.id,
        action="application.pipeline",
        entity_type="application",
        entity_id=str(application.id),
        opportunity_id=opportunity.id,
        application_id=application.id,
        metadata={"from": old_state, "to": target_state, "notes": bool(application.pipeline_notes)},
    )

    applicant = await User.get(application.user_id)
    user_map = {str(applicant.id): applicant} if applicant else {}
    return _serialize_application_row(application=application, opportunity=opportunity, user_map=user_map)


@router.get("/audit-logs", response_model=list[RecruiterAuditLogResponse])
async def list_recruiter_audit_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=5000),
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    query_filters: list[Any] = [RecruiterAuditLog.recruiter_user_id == current_user.id]
    if action:
        query_filters.append(RecruiterAuditLog.action == action.strip())
    if entity_type:
        query_filters.append(RecruiterAuditLog.entity_type == entity_type.strip())

    rows = await RecruiterAuditLog.find_many(*query_filters).sort("-created_at").limit(limit).to_list()
    return [
        RecruiterAuditLogResponse(
            id=str(row.id),
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            opportunity_id=str(row.opportunity_id) if row.opportunity_id else None,
            application_id=str(row.application_id) if row.application_id else None,
            metadata=dict(row.metadata or {}),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/dashboard/summary", response_model=EmployerDashboardSummary)
async def employer_dashboard_summary(
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    opportunities = await _load_employer_opportunities(current_user.id)
    opportunity_ids = [item.id for item in opportunities]
    applications = await _load_applications_for_opportunities(opportunity_ids)

    user_ids = list({application.user_id for application in applications})
    users = await User.find_many(In(User.id, user_ids)).to_list() if user_ids else []
    user_map = {str(user.id): user for user in users}
    opportunity_map = {str(item.id): item for item in opportunities}

    submitted_count = sum(1 for item in applications if item.status.lower() == "submitted")
    pending_count = sum(1 for item in applications if item.status.lower() == "pending manual")
    auto_filled_count = sum(1 for item in applications if item.status.lower() == "auto-filled")
    shortlisted_count = sum(1 for item in applications if _coerce_pipeline_state(item.pipeline_state, default="applied") == "shortlisted")
    rejected_count = sum(1 for item in applications if _coerce_pipeline_state(item.pipeline_state, default="applied") == "rejected")
    interview_count = sum(1 for item in applications if _coerce_pipeline_state(item.pipeline_state, default="applied") == "interview")

    recent_rows: list[EmployerApplicationResponse] = []
    for application in applications[:20]:
        opportunity = opportunity_map.get(str(application.opportunity_id))
        if not opportunity:
            continue
        recent_rows.append(_serialize_application_row(application=application, opportunity=opportunity, user_map=user_map))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    active_opportunities = sum(
        1
        for item in opportunities
        if (item.lifecycle_status or "published") == "published" and (item.deadline is None or item.deadline >= now)
    )

    return EmployerDashboardSummary(
        company_name=_normalize_company_name(profile=profile, user=current_user),
        opportunities_posted=len(opportunities),
        active_opportunities=active_opportunities,
        total_applications=len(applications),
        submitted_applications=submitted_count,
        pending_applications=pending_count,
        auto_filled_applications=auto_filled_count,
        shortlisted_applications=shortlisted_count,
        rejected_applications=rejected_count,
        interview_applications=interview_count,
        recent_applications=recent_rows,
    )
