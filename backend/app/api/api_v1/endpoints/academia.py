"""Academician and institution portals.

Two roles problem statement 26044 asks for that this platform had no concept of.

Academicians get the opportunities aimed at them rather than at their students -
FDPs, faculty internships, industrial training, consultancy and collaborative
research. Same corpus, different slice; a faculty member handed the student feed
is being told to apply for an internship.

Institutions get aggregates about their own cohort and nothing else. Every guard
in here exists because this is the one role that reads other people's data:
cohort membership is decided by the service rather than by a query parameter,
and a cohort too small to anonymise is refused rather than shown.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user
from app.core.account_types import FACULTY, INSTITUTION
from app.core.config import settings
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.skill_assessment import SkillAssessment
from app.models.user import User
from app.services.academia_service import (
    MIN_COHORT_SIZE,
    email_domain,
    student_matches_institution,
    summarise_cohort,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# What counts as an academician's opportunity.
#
# A single loose term list does not work here. Matching any of "research",
# "grant" or "conference" pulled 73 results out of the live corpus, most of them
# wrong: "Market Research Intern", "Finance Research Analyst", "Area Vice
# President, South Europe", and a news headline about federal-grant guidelines.
# A faculty member shown a student internship has been handed the same feed with
# a different label on it.
#
# So terms are split. STRONG terms name a faculty opportunity on their own.
# WEAK terms are genuinely faculty-relevant but also describe plenty of student
# and industry roles, so they additionally require academic context.
FACULTY_STRONG_TERMS: tuple[str, ...] = (
    "faculty development",
    "fdp",
    "faculty position",
    "faculty recruitment",
    "postdoc",
    "post doc",
    "post-doctoral",
    "postdoctoral",
    "professor",
    "assistant professor",
    "associate professor",
    "lecturer",
    "consultancy",
    "industrial training",
    "guest lecture",
    "refresher course",
)

FACULTY_WEAK_TERMS: tuple[str, ...] = (
    "research",
    "fellowship",
    "conference",
    "workshop",
    "seminar",
    "symposium",
    "grant",
    "collaborative",
)

FACULTY_CONTEXT_TERMS: tuple[str, ...] = (
    "faculty",
    "academic",
    "university",
    "institute",
    "college",
    "phd",
    "doctoral",
    "scholar",
    "principal investigator",
)

# Unambiguously aimed at students. Present in the text, nothing else saves it.
STUDENT_MARKERS: tuple[str, ...] = (
    "intern",
    "internship",
    "trainee",
    "fresher",
    "undergraduate",
    "entry level",
    "entry-level",
)


def _require_role(user: User, role: str, *, enabled: bool) -> None:
    if not enabled:
        # 404 rather than 403: a disabled portal should not confirm it exists.
        raise HTTPException(status_code=404, detail="Not Found")
    if bool(getattr(user, "is_admin", False)):
        return
    if str(getattr(user, "account_type", "") or "").strip().lower() != role:
        raise HTTPException(status_code=403, detail=f"{role.capitalize()} account required")


def _looks_faculty_facing(opportunity: Opportunity) -> bool:
    haystack = " ".join(
        str(value or "").lower()
        for value in (
            getattr(opportunity, "opportunity_type", ""),
            getattr(opportunity, "title", ""),
            getattr(opportunity, "portal_category", ""),
        )
    )
    if not haystack.strip():
        return False
    # A student marker disqualifies outright: "Market Research Intern" matches
    # "research" and is not a faculty opportunity under any reading.
    if any(marker in haystack for marker in STUDENT_MARKERS):
        return False
    if any(term in haystack for term in FACULTY_STRONG_TERMS):
        return True
    if any(term in haystack for term in FACULTY_WEAK_TERMS):
        return any(term in haystack for term in FACULTY_CONTEXT_TERMS)
    return False


class FacultyOpportunity(BaseModel):
    id: str
    title: str
    opportunity_type: Optional[str] = None
    organisation: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    deadline: Optional[Any] = None


class FacultyFeedResponse(BaseModel):
    total: int
    scanned: int
    opportunities: list[FacultyOpportunity]


@router.get("/faculty/opportunities", response_model=FacultyFeedResponse)
async def faculty_opportunities(
    limit: int = Query(default=40, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    _require_role(current_user, FACULTY, enabled=bool(settings.FACULTY_PORTAL_ENABLED))

    # Paged for the same reason the vector rebuild is: one statement over the
    # whole table competes with the scrape batches and gets starved.
    page_size = 500
    loaded = 0
    matches: list[Opportunity] = []
    scanned = 0
    while True:
        page = await Opportunity.find_many().sort("-created_at").skip(loaded).limit(page_size).to_list()
        if not page:
            break
        loaded += len(page)
        for opportunity in page:
            if str(getattr(opportunity, "opportunity_status", "") or "") != "active":
                continue
            scanned += 1
            if _looks_faculty_facing(opportunity):
                matches.append(opportunity)
        if len(page) < page_size or len(matches) >= limit * 3:
            break

    selected = matches[:limit]
    return FacultyFeedResponse(
        total=len(matches),
        scanned=scanned,
        opportunities=[
            FacultyOpportunity(
                id=str(row.id),
                title=row.title,
                opportunity_type=getattr(row, "opportunity_type", None),
                organisation=getattr(row, "university", None),
                url=getattr(row, "url", None),
                location=getattr(row, "location", None),
                deadline=getattr(row, "deadline", None),
            )
            for row in selected
        ],
    )


class CohortResponse(BaseModel):
    institution: str
    institution_domain: str
    min_cohort_size: int
    # Populated only when the cohort is large enough to report on.
    available: bool
    reason: Optional[str] = None
    cohort_size: Optional[int] = None
    matched_by_domain: Optional[int] = None
    matched_by_name: Optional[int] = None
    profiles_complete: Optional[int] = None
    assessments_taken: Optional[int] = None
    average_readiness: Optional[float] = None
    average_incoscore: Optional[float] = None
    applications_total: Optional[int] = None
    students_with_applications: Optional[int] = None
    top_gaps: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/institution/cohort", response_model=CohortResponse)
async def institution_cohort(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    _require_role(current_user, INSTITUTION, enabled=bool(settings.INSTITUTION_PORTAL_ENABLED))

    institution_profile = await Profile.find_one(Profile.user_id == current_user.id)
    # The institution's identity comes from its own account, never from a query
    # parameter. Letting the caller name the institution would make this
    # endpoint a way to read any college's cohort.
    institution_name = str(getattr(institution_profile, "college_name", None) or "").strip()
    institution_domain = email_domain(getattr(current_user, "email", ""))

    if not institution_name and not institution_domain:
        raise HTTPException(
            status_code=400,
            detail="Set your institution name on your profile before viewing the cohort.",
        )

    rows: list[dict[str, Any]] = []
    students = await User.find_many().to_list()
    for student in students:
        if str(getattr(student, "account_type", "") or "").strip().lower() != "candidate":
            continue
        profile = await Profile.find_one(Profile.user_id == student.id)
        match = student_matches_institution(
            student_email=getattr(student, "email", ""),
            student_college=getattr(profile, "college_name", None) if profile else None,
            institution_domain=institution_domain,
            institution_name=institution_name,
        )
        if not match.matched:
            continue

        latest = (
            await SkillAssessment.find_many(SkillAssessment.user_id == student.id)
            .sort("-created_at")
            .limit(1)
            .to_list()
        )
        assessment = latest[0] if latest else None
        rows.append(
            {
                "matched_by": match.reason,
                "profile_complete": bool(getattr(profile, "onboarding_completed", False)) if profile else False,
                "incoscore": getattr(profile, "incoscore", None) if profile else None,
                "readiness": getattr(assessment, "readiness_score", None) if assessment else None,
                "gaps": getattr(assessment, "gaps", None) if assessment else None,
                "applications": await Application.find_many(
                    Application.user_id == student.id
                ).count(),
            }
        )

    aggregate, refusal = summarise_cohort(rows)
    if aggregate is None:
        return CohortResponse(
            institution=institution_name or institution_domain,
            institution_domain=institution_domain,
            min_cohort_size=MIN_COHORT_SIZE,
            available=False,
            reason=refusal,
        )

    return CohortResponse(
        institution=institution_name or institution_domain,
        institution_domain=institution_domain,
        min_cohort_size=MIN_COHORT_SIZE,
        available=True,
        cohort_size=aggregate.cohort_size,
        matched_by_domain=aggregate.matched_by_domain,
        matched_by_name=aggregate.matched_by_name,
        profiles_complete=aggregate.profiles_complete,
        assessments_taken=aggregate.assessments_taken,
        average_readiness=aggregate.average_readiness,
        average_incoscore=aggregate.average_incoscore,
        applications_total=aggregate.applications_total,
        students_with_applications=aggregate.students_with_applications,
        top_gaps=aggregate.top_gaps,
    )
