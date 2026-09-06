"""Skill assessment, gap analysis and what to do about them.

The questionnaire is generated from live postings rather than authored, so these
endpoints are thin: the interesting decisions live in skill_demand (what
industry asks for) and skill_assessment_service (what the student can evidence).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_active_user
from app.models.learning_program import LearningProgram
from app.models.profile import Profile
from app.models.skill_assessment import (
    MAX_PROFICIENCY,
    PROFICIENCY_LEVELS,
    SkillAssessment,
)
from app.models.user import User
from app.services import skill_demand as demand_module
from app.services.skill_assessment_service import analyse, build_questionnaire

logger = logging.getLogger(__name__)

router = APIRouter()


class QuestionnaireQuestion(BaseModel):
    skill: str
    is_soft: bool
    demand_share: float
    rationale: str


class QuestionnaireResponse(BaseModel):
    domain: str
    # The domain the questions actually came from. Differs from `domain` when a
    # thin domain fell back to the whole market, and the student should be able
    # to see that rather than wonder why they were asked about React.
    sourced_from: str
    postings_analysed: int
    scale: dict[int, str]
    questions: list[QuestionnaireQuestion]


class AssessmentSubmission(BaseModel):
    domain: Optional[str] = Field(default=None, max_length=120)
    # {skill: 0..4}
    responses: dict[str, int] = Field(default_factory=dict)


class GapRow(BaseModel):
    skill: str
    level: int
    demand_share: float
    is_soft: bool
    priority: float
    corroborated: bool


class BriefingResponse(BaseModel):
    """A grounded reading of this student's own result.

    `source` is surfaced: "llm" when the model's answer passed number
    verification, "deterministic" when it was unavailable or rejected,
    "refused" when too little of the assessment is finished to plan from.
    """

    headline: str
    paragraphs: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    source: str = "deterministic"
    refusal: Optional[str] = None


class AssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    domain: str
    readiness_score: float
    strengths: list[GapRow]
    gaps: list[GapRow]
    adjustments: list[dict[str, Any]]
    #: What to do about the gaps, ranked by what actually moves this student's
    #: odds. The score and the gap list are the measurement; this is the part a
    #: student would otherwise have to work out alone.
    briefing: Optional[BriefingResponse] = None


async def _resolve_domain(user: User, requested: Optional[str]) -> str:
    if requested and requested.strip():
        return requested.strip()
    profile = await Profile.find_one(Profile.user_id == user.id)
    return str(getattr(profile, "domain", None) or "").strip() or demand_module.GLOBAL_DOMAIN


async def _readiness_briefing(
    *, readiness: float, strengths: list[Any], gaps: list[Any], domain: str
) -> Optional["BriefingResponse"]:
    """Build the plan, and never let it take the result down with it.

    A student who has just finished an assessment must see their score. If the
    narration fails for any reason - provider down, verification rejected the
    answer, anything - the measurement is still theirs.
    """
    from app.services.role_briefings import student_readiness_plan

    try:
        programmes = (
            await LearningProgram.find_many(LearningProgram.status == "published")
            .limit(6)
            .to_list()
        )
    except Exception:
        programmes = []

    try:
        answer = await student_readiness_plan(
            readiness=readiness,
            gaps=[dict(row) if isinstance(row, dict) else dict(vars(row)) for row in gaps],
            strengths=[dict(row) if isinstance(row, dict) else dict(vars(row)) for row in strengths],
            programmes=[
                {"title": row.title, "skills_taught": list(row.skills_taught or [])}
                for row in programmes
            ],
            domain=domain,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Readiness briefing failed, serving the assessment alone: %s", exc)
        return None
    return BriefingResponse(**{
        key: value for key, value in answer.to_dict().items() if key != "rejected_because"
    })


@router.get("/questionnaire", response_model=QuestionnaireResponse)
async def get_questionnaire(
    domain: Optional[str] = Query(default=None, max_length=120),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    resolved = await _resolve_domain(current_user, domain)
    snapshot = await demand_module.latest_snapshot(resolved)
    if snapshot is None:
        # Never fabricate questions. An assessment built from nothing would look
        # identical to a real one and produce advice with no basis at all.
        raise HTTPException(
            status_code=503,
            detail="Skill demand has not been computed yet. Try again shortly.",
        )

    questions = build_questionnaire(snapshot.skills)
    return QuestionnaireResponse(
        domain=resolved,
        sourced_from=snapshot.domain,
        postings_analysed=snapshot.postings_analysed,
        scale=PROFICIENCY_LEVELS,
        questions=[
            QuestionnaireQuestion(
                skill=item.skill,
                is_soft=item.is_soft,
                demand_share=item.demand_share,
                rationale=item.rationale,
            )
            for item in questions
        ],
    )


@router.post("/assessment", response_model=AssessmentResponse)
async def submit_assessment(
    payload: AssessmentSubmission,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    if not payload.responses:
        raise HTTPException(status_code=400, detail="responses must not be empty")
    for skill, level in payload.responses.items():
        if not isinstance(level, int) or level < 0 or level > MAX_PROFICIENCY:
            raise HTTPException(
                status_code=400,
                detail=f"level for '{skill}' must be an integer between 0 and {MAX_PROFICIENCY}",
            )

    resolved = await _resolve_domain(current_user, payload.domain)
    snapshot = await demand_module.latest_snapshot(resolved)
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail="Skill demand has not been computed yet. Try again shortly.",
        )

    profile = await Profile.find_one(Profile.user_id == current_user.id)
    result = analyse(
        domain=resolved,
        responses=payload.responses,
        demand_rows=snapshot.skills,
        profile=profile,
    )

    record = SkillAssessment(
        user_id=current_user.id,
        domain=resolved,
        responses=result.responses,
        corroborated=result.corroborated,
        strengths=[vars(item) for item in result.strengths],
        gaps=[vars(item) for item in result.gaps],
        readiness_score=result.readiness_score,
        demand_snapshot_id=str(snapshot.id),
    )
    await record.insert()

    return AssessmentResponse(
        id=str(record.id),
        domain=result.domain,
        readiness_score=result.readiness_score,
        strengths=[GapRow(**vars(item)) for item in result.strengths],
        gaps=[GapRow(**vars(item)) for item in result.gaps],
        adjustments=result.adjustments,
        briefing=await _readiness_briefing(
            readiness=result.readiness_score,
            strengths=[vars(item) for item in result.strengths],
            gaps=[vars(item) for item in result.gaps],
            domain=result.domain,
        ),
    )


@router.get("/assessment/latest", response_model=Optional[AssessmentResponse])
async def latest_assessment(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    rows = (
        await SkillAssessment.find_many(SkillAssessment.user_id == current_user.id)
        .sort("-created_at")
        .limit(1)
        .to_list()
    )
    if not rows:
        return None
    record = rows[0]
    return AssessmentResponse(
        id=str(record.id),
        domain=record.domain,
        readiness_score=record.readiness_score,
        strengths=[GapRow(**row) for row in record.strengths],
        gaps=[GapRow(**row) for row in record.gaps],
        adjustments=[],
        briefing=await _readiness_briefing(
            readiness=record.readiness_score,
            strengths=list(record.strengths or []),
            gaps=list(record.gaps or []),
            domain=record.domain,
        ),
    )


@router.get("/demand", response_model=dict)
async def read_demand(
    domain: Optional[str] = Query(default=None, max_length=120),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """The demand table itself, so a student can see what drives the advice."""
    resolved = await _resolve_domain(current_user, domain)
    snapshot = await demand_module.latest_snapshot(resolved)
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Skill demand has not been computed yet.")
    return {
        "domain": resolved,
        "sourced_from": snapshot.domain,
        "postings_analysed": snapshot.postings_analysed,
        "postings_with_skills": snapshot.postings_with_skills,
        "computed_at": snapshot.created_at,
        "skills": snapshot.skills,
    }
