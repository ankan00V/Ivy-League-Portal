from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from beanie import PydanticObjectId
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_employer_user
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User

router = APIRouter()


class EmployerOpportunityCreate(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    description: str = Field(min_length=20, max_length=8000)
    application_url: str = Field(min_length=8, max_length=1200)
    opportunity_type: str = Field(default="Job", min_length=2, max_length=80)
    domain: Optional[str] = Field(default=None, max_length=160)
    deadline: Optional[datetime] = None
    location: Optional[str] = Field(default=None, max_length=200)
    eligibility: Optional[str] = Field(default=None, max_length=600)


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
    submitted_at: Optional[datetime] = None
    created_at: datetime


class EmployerDashboardSummary(BaseModel):
    company_name: Optional[str] = None
    opportunities_posted: int
    active_opportunities: int
    total_applications: int
    submitted_applications: int
    pending_applications: int
    auto_filled_applications: int
    recent_applications: list[EmployerApplicationResponse]


def _normalize_company_name(*, profile: Optional[Profile], user: User) -> str:
    candidate = (profile.company_name if profile else None) or user.full_name or "Employer Organization"
    text = str(candidate).strip()
    return text or "Employer Organization"


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
        created_at=opportunity.created_at,
        applications_count=int(applications_count),
    )


async def _load_employer_opportunities(user_id: PydanticObjectId) -> list[Opportunity]:
    return await Opportunity.find_many(Opportunity.posted_by_user_id == user_id).sort("-created_at").to_list()


async def _load_applications_for_opportunities(opportunity_ids: list[PydanticObjectId]) -> list[Application]:
    if not opportunity_ids:
        return []
    return await Application.find_many(In(Application.opportunity_id, opportunity_ids)).sort("-created_at").to_list()


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
    opportunity = Opportunity(
        title=payload.title.strip(),
        description=payload.description.strip(),
        url=cleaned_url,
        opportunity_type=payload.opportunity_type.strip(),
        domain=(payload.domain or "").strip() or None,
        university=company_name,
        source="employer_portal",
        location=(payload.location or "").strip() or None,
        eligibility=(payload.eligibility or "").strip() or None,
        deadline=payload.deadline,
        is_employer_post=True,
        posted_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    await opportunity.insert()
    return _opportunity_to_response(opportunity=opportunity, applications_count=0)


@router.get("/opportunities", response_model=list[EmployerOpportunityResponse])
async def list_employer_opportunities(
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    opportunities = await _load_employer_opportunities(current_user.id)
    opportunity_ids = [item.id for item in opportunities]
    applications = await _load_applications_for_opportunities(opportunity_ids)

    counts: dict[str, int] = {}
    for app in applications:
        key = str(app.opportunity_id)
        counts[key] = counts.get(key, 0) + 1

    return [
        _opportunity_to_response(opportunity=item, applications_count=counts.get(str(item.id), 0))
        for item in opportunities
    ]


@router.get("/opportunities/{opportunity_id}/applications", response_model=list[EmployerApplicationResponse])
async def list_employer_opportunity_applications(
    opportunity_id: str,
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

    rows: list[EmployerApplicationResponse] = []
    for application in applications:
        applicant = user_map.get(str(application.user_id))
        rows.append(
            EmployerApplicationResponse(
                application_id=str(application.id),
                opportunity_id=str(opportunity.id),
                opportunity_title=opportunity.title,
                applicant_user_id=str(application.user_id),
                applicant_name=applicant.full_name if applicant else None,
                applicant_email=applicant.email if applicant else None,
                status=application.status,
                submitted_at=application.submitted_at,
                created_at=application.created_at,
            )
        )
    return rows


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

    recent_rows: list[EmployerApplicationResponse] = []
    for application in applications[:20]:
        opportunity = opportunity_map.get(str(application.opportunity_id))
        if not opportunity:
            continue
        applicant = user_map.get(str(application.user_id))
        recent_rows.append(
            EmployerApplicationResponse(
                application_id=str(application.id),
                opportunity_id=str(opportunity.id),
                opportunity_title=opportunity.title,
                applicant_user_id=str(application.user_id),
                applicant_name=applicant.full_name if applicant else None,
                applicant_email=applicant.email if applicant else None,
                status=application.status,
                submitted_at=application.submitted_at,
                created_at=application.created_at,
            )
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    active_opportunities = sum(
        1
        for item in opportunities
        if item.deadline is None or item.deadline >= now
    )

    return EmployerDashboardSummary(
        company_name=_normalize_company_name(profile=profile, user=current_user),
        opportunities_posted=len(opportunities),
        active_opportunities=active_opportunities,
        total_applications=len(applications),
        submitted_applications=submitted_count,
        pending_applications=pending_count,
        auto_filled_applications=auto_filled_count,
        recent_applications=recent_rows,
    )
