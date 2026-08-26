"""Skill assessment records and the demand table they are scored against.

Two documents, deliberately separate:

SkillDemandSnapshot is what industry is asking for, derived from the live
corpus. It belongs to a domain, not to a student, and is rebuilt on a schedule
as the scrapers bring in new postings.

SkillAssessment is one student's answers and the profile derived from them. It
keeps the demand snapshot it was scored against rather than recomputing on read:
a student who is told "you are missing Docker" and comes back a week later to
find the advice silently changed - because the corpus moved, not because they
did - has been given no advice at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.time import utc_now

# Self-rating scale. Deliberately short: finer scales invite students to agonise
# over 6 vs 7 without making the result more informative.
PROFICIENCY_LEVELS = {
    0: "none",
    1: "aware",
    2: "practising",
    3: "confident",
    4: "expert",
}
MAX_PROFICIENCY = 4


class SkillDemandSnapshot(Document):
    """Ranked skill demand for one domain, derived from live postings."""

    domain: str = Field(json_schema_extra={"index": True}, min_length=1, max_length=120)
    # Rows of {skill, postings, share, is_soft}, ranked by share descending.
    skills: list[dict[str, Any]] = Field(default_factory=list)
    postings_analysed: int = Field(default=0, ge=0)
    # Postings that produced at least one usable skill. Held separately because
    # extraction covers well under half the corpus, and a share computed over
    # everything reads far lower than the same skill's real prominence.
    postings_with_skills: int = Field(default=0, ge=0)
    corpus_version: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "skill_demand_snapshots"
        indexes = [
            IndexModel([("domain", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]


class SkillAssessment(Document):
    """One student's completed assessment and the gaps derived from it."""

    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    domain: str = Field(min_length=1, max_length=120)
    # {skill: 0..4} exactly as the student answered.
    responses: dict[str, int] = Field(default_factory=dict)
    # {skill: 0..4} after corroborating each answer against profile evidence.
    corroborated: dict[str, int] = Field(default_factory=dict)
    strengths: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    # Overall readiness for the chosen domain, 0..100.
    readiness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    # The snapshot this was scored against, so the advice stays reproducible
    # even after the corpus moves underneath it.
    demand_snapshot_id: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    @field_validator("responses", "corroborated")
    @classmethod
    def clamp_levels(cls, value: dict[str, int]) -> dict[str, int]:
        # A level outside the scale silently distorts every gap computed from
        # it, and the arithmetic downstream has no way to notice.
        cleaned: dict[str, int] = {}
        for skill, level in (value or {}).items():
            name = str(skill or "").strip().lower()
            if not name:
                continue
            try:
                numeric = int(level)
            except (TypeError, ValueError):
                continue
            cleaned[name] = max(0, min(MAX_PROFICIENCY, numeric))
        return cleaned

    class Settings:
        name = "skill_assessments"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
