"""Industry learning programmes, and matching them to a student's gaps.

Publishing reuses the employer portal's verification gate rather than inventing
a second one. A programme is a claim about training a student will spend weeks
on; the reason an unverified account cannot put a job in front of them is
exactly the reason it cannot put a course in front of them either.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_active_user, get_current_employer_user
from app.core.time import utc_now
from app.models.learning_program import LearningProgram
from app.models.skill_assessment import SkillAssessment
from app.models.user import User
from app.services.learning_recommender import recommend_programs

logger = logging.getLogger(__name__)

router = APIRouter()


class ProgramCreate(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    description: str = Field(min_length=20, max_length=8000)
    provider: str = Field(min_length=2, max_length=200)
    url: Optional[str] = Field(default=None, max_length=1200)
    program_format: Literal["course", "certification", "workshop", "mentorship", "bootcamp"] = "course"
    delivery_mode: Literal["online", "offline", "hybrid"] = "online"
    duration_weeks: Optional[int] = Field(default=None, ge=0, le=520)
    is_free: bool = True
    cost_inr: Optional[int] = Field(default=None, ge=0)
    certificate_offered: bool = False
    skills_taught: list[str] = Field(default_factory=list, max_length=40)
    status: Literal["draft", "published"] = "draft"


class ProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    provider: str
    description: str
    url: Optional[str] = None
    program_format: str
    delivery_mode: str
    duration_weeks: Optional[int] = None
    is_free: bool
    certificate_offered: bool
    skills_taught: list[str]
    status: str


class RecommendationRow(BaseModel):
    program_id: str
    title: str
    provider: str
    url: Optional[str] = None
    program_format: str
    duration_weeks: Optional[int] = None
    is_free: bool
    certificate_offered: bool
    closes_gaps: list[str]
    score: float


class RecommendationResponse(BaseModel):
    #: Named so an empty list is never ambiguous: no assessment, no gaps left,
    #: or no programme yet published are three different situations and the UI
    #: has to say which.
    status: Literal["ok", "no_assessment", "no_programs", "no_matching_programs"]
    detail: str
    recommendations: list[RecommendationRow] = Field(default_factory=list)


def _to_response(program: LearningProgram) -> ProgramResponse:
    return ProgramResponse(
        id=str(program.id),
        title=program.title,
        provider=program.provider,
        description=program.description,
        url=program.url,
        program_format=program.program_format,
        delivery_mode=program.delivery_mode,
        duration_weeks=program.duration_weeks,
        is_free=program.is_free,
        certificate_offered=program.certificate_offered,
        skills_taught=list(program.skills_taught or []),
        status=program.status,
    )


@router.post("/programs", response_model=ProgramResponse)
async def create_program(
    payload: ProgramCreate,
    current_user: User = Depends(get_current_employer_user),
) -> Any:
    # Imported here rather than at module scope: the employer endpoints module
    # owns this gate, and importing it at the top would make these two modules
    # import each other.
    from app.api.api_v1.endpoints.employer import _require_verified_employer

    if payload.status == "published":
        await _require_verified_employer(current_user)

    if not payload.skills_taught:
        # A programme with no skills cannot be matched to a gap, so it would be
        # published into a recommender that can never surface it. Refusing is
        # more honest than accepting something that will never be seen.
        raise HTTPException(
            status_code=400,
            detail="skills_taught is required: it is what matches this programme to a student's gaps.",
        )

    now = utc_now()
    program = LearningProgram(
        title=payload.title.strip(),
        description=payload.description.strip(),
        provider=payload.provider.strip(),
        url=(payload.url or "").strip() or None,
        program_format=payload.program_format,
        delivery_mode=payload.delivery_mode,
        duration_weeks=payload.duration_weeks,
        is_free=payload.is_free,
        cost_inr=payload.cost_inr,
        certificate_offered=payload.certificate_offered,
        skills_taught=payload.skills_taught,
        posted_by_user_id=current_user.id,
        status=payload.status,
        published_at=now if payload.status == "published" else None,
        created_at=now,
        updated_at=now,
    )
    await program.insert()
    return _to_response(program)


@router.get("/programs", response_model=list[ProgramResponse])
async def list_programs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    rows = (
        await LearningProgram.find_many(LearningProgram.status == "published")
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    return [_to_response(row) for row in rows]


@router.get("/recommended", response_model=RecommendationResponse)
async def recommended_programs(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    latest = (
        await SkillAssessment.find_many(SkillAssessment.user_id == current_user.id)
        .sort("-created_at")
        .limit(1)
        .to_list()
    )
    if not latest:
        return RecommendationResponse(
            status="no_assessment",
            detail="Take the skill assessment first — recommendations are built from your gaps.",
        )

    gaps = list(latest[0].gaps or [])
    if not gaps:
        return RecommendationResponse(
            status="no_assessment" if not latest[0].responses else "no_matching_programs",
            detail="Your last assessment found no gaps to close.",
        )

    programs = (
        await LearningProgram.find_many(LearningProgram.status == "published")
        .sort("-created_at")
        .limit(500)
        .to_list()
    )
    if not programs:
        return RecommendationResponse(
            status="no_programs",
            detail="No industry learning programmes have been published yet.",
        )

    matches = recommend_programs(gaps=gaps, programs=programs, limit=limit)
    if not matches:
        return RecommendationResponse(
            status="no_matching_programs",
            detail="No published programme covers your current gaps.",
        )

    return RecommendationResponse(
        status="ok",
        detail=f"{len(matches)} programme(s) matched to your gaps.",
        recommendations=[RecommendationRow(**vars(match)) for match in matches],
    )
