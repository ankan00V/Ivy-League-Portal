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
import asyncio

from beanie.operators import In

from app.core.audiences import FACULTY as AUDIENCE_FACULTY, audience_matches
from app.core.config import settings
from app.models.application import Application
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.skill_assessment import SkillAssessment
from app.models.user import User
from app.services.curriculum_signal import (
    MIN_ASSESSED_FOR_COVERAGE,
    build_funnel,
    build_signal,
)
from app.services.skill_demand import latest_snapshot as latest_demand_snapshot
from app.services.role_briefings import faculty_field_brief, institution_curriculum_brief
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

# Opportunity types that can plausibly carry an academician's opening. Used to
# narrow the salvage pass before the keyword test runs, so it reads hundreds of
# rows rather than the whole corpus.
# Measured on the live corpus: these five types hold 35 active rows in total,
# and every faculty-facing row the keyword pass has ever found is a Scholarship
# or a Research posting. "Job" was in this list briefly and had to come out - it
# is the largest type in the corpus, so including it meant the row limit filled
# with student jobs before reaching a single one of the 35.
FACULTY_CANDIDATE_TYPES: tuple[str, ...] = (
    "Conference",
    "Research",
    "Scholarship",
    "Workshop",
    "Fellowship",
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


class DemandRow(BaseModel):
    skill: str
    postings: int
    share: float
    is_soft: bool


class BriefingResponse(BaseModel):
    """A grounded reading of the numbers on the same page.

    `source` is surfaced rather than hidden: "llm" when the model's answer
    passed number verification, "deterministic" when it was unavailable or
    rejected, "refused" below the evidence floor. A reader deciding how much
    weight to give a paragraph deserves to know what wrote it.
    """

    headline: str
    paragraphs: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    source: str = "deterministic"
    refusal: Optional[str] = None


class FacultyFeedResponse(BaseModel):
    total: int
    scanned: int
    #: What industry is currently advertising for, so an academician can see
    #: what their teaching is preparing students for. The problem statement asks
    #: for exactly this - "align teaching with current industry practices" - and
    #: it is the half of an academician's job this platform can actually inform.
    demand_signal: list[DemandRow] = Field(default_factory=list)
    demand_domain: Optional[str] = None
    demand_postings_analysed: int = 0
    #: How many came from sources that serve academicians, versus rescued from
    #: the student corpus by keyword. The second number shrinking towards zero
    #: is what "faculty sources are working" looks like.
    from_faculty_sources: int = 0
    from_keyword_fallback: int = 0
    opportunities: list[FacultyOpportunity]
    briefing: Optional[BriefingResponse] = None


@router.get("/faculty/opportunities", response_model=FacultyFeedResponse)
async def faculty_opportunities(
    limit: int = Query(default=40, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    _require_role(current_user, FACULTY, enabled=bool(settings.FACULTY_PORTAL_ENABLED))

    # Two passes, in priority order, and neither scans the whole corpus.
    #
    # This used to page through every opportunity in the database - 2,110 rows
    # in pages of 500 - and decide in Python. That cost ~8 seconds on a page a
    # faculty member opens first. `audience` is an indexed column now, so the
    # rows that belong here are fetched directly.
    #
    # The keyword pass stays as a salvage operation over student rows, because
    # faculty sources are not yet producing and the corpus does occasionally
    # carry a professorship a student scraper picked up. It is bounded to a
    # recent window rather than the whole table: an opening from two years ago
    # is not worth eight seconds of somebody's time.
    by_audience = (
        await Opportunity.find_many(Opportunity.audience == AUDIENCE_FACULTY)
        .sort("-created_at")
        .limit(limit * 3)
        .to_list()
    )
    by_audience = [
        row for row in by_audience
        if str(getattr(row, "opportunity_status", "") or "") == "active"
    ]

    by_keyword: list[Opportunity] = []
    scanned = len(by_audience)
    if len(by_audience) < limit:
        # Narrowed by type before the keyword test rather than by recency.
        # A recency window was the first attempt and it was wrong: the real
        # faculty-facing rows in this corpus are older than the most recent 600,
        # so it returned nothing and looked fast doing it. Type is the field
        # that actually correlates - every one of them is a Conference,
        # Research, Scholarship, Workshop or Fellowship row - so this reads a
        # few hundred candidates instead of every opportunity ever scraped.
        # No recency cap. The set is 35 rows, and the matches in it happen to
        # be among the oldest in the corpus - a "most recent 600" window was the
        # first attempt here and returned nothing at all while looking fast.
        window = await Opportunity.find_many(
            In(Opportunity.opportunity_type, list(FACULTY_CANDIDATE_TYPES))
        ).to_list()
        scanned += len(window)
        seen = {str(row.id) for row in by_audience}
        for opportunity in window:
            if str(getattr(opportunity, "opportunity_status", "") or "") != "active":
                continue
            if str(opportunity.id) in seen:
                continue
            if _looks_faculty_facing(opportunity):
                by_keyword.append(opportunity)

    matches = by_audience + by_keyword

    selected = matches[:limit]

    # The demand table for this academician's own department, falling back to
    # the wider market. Read here rather than on a separate endpoint so the page
    # costs one round trip instead of two - at ~350ms each that is the
    # difference between a page that feels instant and one that does not.
    profile = await Profile.find_one(Profile.user_id == current_user.id)
    department = str(getattr(profile, "specialisation", None) or getattr(profile, "department", None) or "").strip()
    snapshot = await latest_demand_snapshot(department or "")

    demand_rows = [
        DemandRow(
            skill=str(row.get("skill") or ""),
            postings=int(row.get("postings") or 0),
            share=float(row.get("share") or 0.0),
            is_soft=bool(row.get("is_soft", False)),
        )
        for row in (getattr(snapshot, "skills", None) or [])[:12]
    ]
    feed_rows = [
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
    ]

    briefing = None
    try:
        answer = await faculty_field_brief(
            demand=[row.model_dump() for row in demand_rows],
            opportunities=[row.model_dump() for row in feed_rows],
            department=department,
            specialisation=getattr(profile, "specialisation", None) if profile else None,
        )
        briefing = BriefingResponse(**{
            key: value for key, value in answer.to_dict().items() if key != "rejected_because"
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Faculty briefing failed, serving the feed alone: %s", exc)

    return FacultyFeedResponse(
        total=len(matches),
        scanned=scanned,
        briefing=briefing,
        demand_signal=demand_rows,
        demand_domain=getattr(snapshot, "domain", None),
        demand_postings_analysed=int(getattr(snapshot, "postings_analysed", 0) or 0),
        from_faculty_sources=len(by_audience),
        from_keyword_fallback=len(by_keyword),
        opportunities=feed_rows,
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
    #: Where the cohort stops progressing. Absolute counts alone cannot say
    #: whether students fail to get offers or never finish a profile, and those
    #: have completely different remedies.
    funnel: list[dict[str, Any]] = Field(default_factory=list)
    #: Live demand against what this cohort can evidence. The one view here that
    #: no job board can produce, and the problem statement's actual ask.
    curriculum_signal: list[dict[str, Any]] = Field(default_factory=list)
    signal_domain: Optional[str] = None
    #: Why the signal is empty, when it is. A hidden section reads as broken,
    #: and "not enough students assessed yet" is a different problem from "your
    #: students have no gaps" - the first is fixed by asking them to take the
    #: assessment, the second not at all.
    signal_reason: Optional[str] = None
    #: The argument, not the table. An institution taking a syllabus change to
    #: an academic council needs a case they can defend in a room, and fifteen
    #: rows of percentages is where that work starts rather than ends.
    briefing: Optional[BriefingResponse] = None


def institution_domain_for_signal(rows: list[dict[str, Any]]) -> str:
    """Which demand table to measure this cohort against.

    Students in one institution sit across many domains, so there is no single
    right answer. The whole-market table is used rather than picking one
    student's domain and calling it the institution's - a curriculum argument
    built on an arbitrary choice is worse than one built on the widest evidence
    available.
    """
    from app.services.skill_demand import GLOBAL_DOMAIN

    return GLOBAL_DOMAIN


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

    # Four queries for the whole cohort, not three per student.
    #
    # This loop used to call Profile.find_one, SkillAssessment.find_many and
    # Application.count once per student. At ~350ms a round trip that is a
    # second and a bit per student: fine for the eight accounts in this
    # database, eight minutes for an institution with five hundred - and the
    # institutions this feature exists for are the large ones.
    students = [
        student
        for student in await User.find_many().to_list()
        if str(getattr(student, "account_type", "") or "").strip().lower() == "candidate"
    ]
    student_ids = [student.id for student in students]
    if not student_ids:
        profiles, assessments, applications = [], [], []
    else:
        profiles, assessments, applications = await asyncio.gather(
            Profile.find_many(In(Profile.user_id, student_ids)).to_list(),
            SkillAssessment.find_many(In(SkillAssessment.user_id, student_ids))
            .sort("-created_at")
            .to_list(),
            Application.find_many(In(Application.user_id, student_ids)).to_list(),
        )

    profile_by_user = {str(row.user_id): row for row in profiles}
    # Sorted newest first above, so the first one seen per student is the latest.
    latest_assessment: dict[str, Any] = {}
    for row in assessments:
        latest_assessment.setdefault(str(row.user_id), row)
    application_counts: dict[str, int] = {}
    for row in applications:
        key = str(row.user_id)
        application_counts[key] = application_counts.get(key, 0) + 1

    rows: list[dict[str, Any]] = []
    corroborated_levels: list[dict[str, Any]] = []
    for student in students:
        key = str(student.id)
        profile = profile_by_user.get(key)
        match = student_matches_institution(
            student_email=getattr(student, "email", ""),
            student_college=getattr(profile, "college_name", None) if profile else None,
            institution_domain=institution_domain,
            institution_name=institution_name,
        )
        if not match.matched:
            continue

        assessment = latest_assessment.get(key)
        if assessment is not None and getattr(assessment, "corroborated", None):
            # The corroborated map, not the raw answers: an institution shown
            # its students' self-belief instead of what they can evidence would
            # be reading the wrong number entirely.
            corroborated_levels.append(dict(assessment.corroborated))

        rows.append(
            {
                "matched_by": match.reason,
                "profile_complete": bool(getattr(profile, "onboarding_completed", False)) if profile else False,
                "incoscore": getattr(profile, "incoscore", None) if profile else None,
                "readiness": getattr(assessment, "readiness_score", None) if assessment else None,
                "gaps": getattr(assessment, "gaps", None) if assessment else None,
                "applications": application_counts.get(key, 0),
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

    # Cross live demand against what this cohort can evidence.
    snapshot = await latest_demand_snapshot(institution_domain_for_signal(rows))
    signal = (
        build_signal(demand_rows=snapshot.skills, assessments=corroborated_levels)
        if snapshot is not None
        else []
    )
    signal_reason = None
    if not signal:
        assessed = len(corroborated_levels)
        if snapshot is None:
            signal_reason = "Skill demand has not been computed yet."
        elif assessed < MIN_ASSESSED_FOR_COVERAGE:
            signal_reason = (
                f"{assessed} of your students have taken the skill assessment. "
                f"At least {MIN_ASSESSED_FOR_COVERAGE} are needed before coverage "
                "means anything - below that a percentage is noise with a decimal point."
            )
        else:
            signal_reason = "No skill has enough assessed students in common to compare yet."

    funnel = build_funnel(
        cohort_size=aggregate.cohort_size,
        profiles_complete=aggregate.profiles_complete,
        assessments_taken=aggregate.assessments_taken,
        students_with_applications=aggregate.students_with_applications,
    )

    funnel_rows = [vars(stage) for stage in funnel]
    signal_rows = [vars(item) for item in signal]

    briefing = None
    try:
        answer = await institution_curriculum_brief(
            signal=signal_rows,
            funnel=funnel_rows,
            cohort_size=aggregate.cohort_size,
            students_assessed=aggregate.assessments_taken,
            institution=institution_name or institution_domain,
        )
        briefing = BriefingResponse(**{
            key: value for key, value in answer.to_dict().items() if key != "rejected_because"
        })
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Institution briefing failed, serving the tables alone: %s", exc)

    return CohortResponse(
        briefing=briefing,
        institution=institution_name or institution_domain,
        institution_domain=institution_domain,
        min_cohort_size=MIN_COHORT_SIZE,
        available=True,
        funnel=funnel_rows,
        curriculum_signal=signal_rows,
        signal_reason=signal_reason,
        signal_domain=getattr(snapshot, "domain", None),
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
