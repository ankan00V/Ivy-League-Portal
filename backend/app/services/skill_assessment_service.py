"""Skill assessment: questionnaire, corroboration, gap analysis.

The questionnaire is generated from the demand snapshot rather than written by
hand, so the questions a student answers are the skills employers are currently
advertising for in their domain. A hand-written question list is really the
author's guess about industry, frozen on the day they typed it.

Corroboration is the part that makes the result mean anything. A self-rated
assessment is a measure of confidence, not competence, and the two diverge in
opposite directions for exactly the students who most need accurate advice.
Every answer is therefore checked against evidence already in the profile -
projects, certifications, experience, declared skills - and an unsupported high
rating is pulled down. The student is told this happened; it is guidance, not a
verdict, and the point is to prompt them to add the evidence.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from app.models.skill_assessment import MAX_PROFICIENCY
from app.services.skill_demand import is_soft_skill, normalise_skill

logger = logging.getLogger(__name__)

# How far an unsupported claim can fall. A student claiming "expert" with no
# corroboration lands at "practising" rather than at zero: absence of evidence
# in a profile is weak evidence of absence, since plenty of real competence
# never makes it into a profile.
UNSUPPORTED_CEILING = 2

# Levels at or above this are treated as a claim strong enough to need backing.
CLAIM_THRESHOLD = 3


@dataclass
class QuestionnaireItem:
    skill: str
    is_soft: bool
    demand_share: float
    # Why this question is being asked, shown to the student.
    rationale: str


@dataclass
class SkillGap:
    skill: str
    level: int
    demand_share: float
    is_soft: bool
    # demand x deficit: what closing this gap is worth, not merely how far
    # behind the student is. Being weak at something nobody asks for is not a
    # gap worth spending a semester on.
    priority: float
    corroborated: bool = True


@dataclass
class AssessmentResult:
    domain: str
    responses: dict[str, int]
    corroborated: dict[str, int]
    strengths: list[SkillGap] = field(default_factory=list)
    gaps: list[SkillGap] = field(default_factory=list)
    readiness_score: float = 0.0
    adjustments: list[dict[str, Any]] = field(default_factory=list)


def build_questionnaire(
    demand_rows: Iterable[dict[str, Any]],
    *,
    max_technical: int = 12,
    max_soft: int = 5,
) -> list[QuestionnaireItem]:
    """Pick the questions worth asking from a domain's demand table.

    Technical and soft skills are quota'd separately rather than taken off one
    ranked list. Soft skills are named in far fewer postings than technical ones
    - they are assumed rather than listed - so a single ranking buries them
    entirely, and the problem statement asks for both.
    """
    technical: list[QuestionnaireItem] = []
    soft: list[QuestionnaireItem] = []

    for row in demand_rows or []:
        skill = normalise_skill(str(row.get("skill") or ""))
        if not skill:
            continue
        share = float(row.get("share") or 0.0)
        postings = int(row.get("postings") or 0)
        item = QuestionnaireItem(
            skill=skill,
            is_soft=bool(row.get("is_soft", is_soft_skill(skill))),
            demand_share=share,
            rationale=f"named in {postings} live posting{'s' if postings != 1 else ''} in this domain",
        )
        bucket = soft if item.is_soft else technical
        if len(bucket) < (max_soft if item.is_soft else max_technical):
            bucket.append(item)

    return technical + soft


def _evidence_terms(profile: Any) -> set[str]:
    """Every skill-ish token the student has already put in their profile.

    Read from the structured entry lists as well as the free-text fields,
    because the structured ones are where a serious student records the work
    that would corroborate a claim.
    """
    terms: set[str] = set()

    def _add(value: Any) -> None:
        if not value:
            return
        for piece in re.split(r"[,;/|\n]+", str(value)):
            cleaned = normalise_skill(piece)
            if cleaned:
                terms.add(cleaned)

    if profile is None:
        return terms

    _add(getattr(profile, "skills", None))
    _add(getattr(profile, "interests", None))
    for tag in getattr(profile, "interest_graph", None) or []:
        _add(tag)

    entry_lists = (
        "project_entries",
        "certification_entries",
        "experience_entries",
        "education_entries",
        "honor_entries",
        "volunteer_entries",
    )
    for name in entry_lists:
        for entry in getattr(profile, name, None) or []:
            # Entries are pydantic models or plain dicts depending on caller.
            getter = entry.get if isinstance(entry, dict) else lambda k, _e=entry: getattr(_e, k, None)
            for skill in getter("skills") or []:
                _add(skill)
            for text_field in ("name", "title", "description", "field_of_study"):
                _add(getter(text_field))

    return terms


def _has_activity_evidence(profile: Any) -> bool:
    """Whether the profile shows real-world activity at all.

    Used only for soft skills, which cannot be corroborated the way technical
    ones are: nobody lists "communication" among a project's skills, so a strict
    name match marks every student weak at every soft skill and the advice
    degrades into telling all of them to work on teamwork. Leading a project,
    volunteering, holding a role or earning an honour is the kind of evidence
    these claims actually come with.
    """
    if profile is None:
        return False
    for name in ("experience_entries", "volunteer_entries", "honor_entries", "project_entries"):
        if getattr(profile, name, None):
            return True
    return False


def corroborate(
    responses: dict[str, int],
    *,
    profile: Any,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Pull down high self-ratings that nothing in the profile supports.

    Returns the adjusted levels and a record of every adjustment, because a
    score that silently disagrees with what the student entered is the kind of
    thing that destroys trust in the whole feature the first time they notice.
    """
    evidence = _evidence_terms(profile)
    has_activity = _has_activity_evidence(profile)
    adjusted: dict[str, int] = {}
    adjustments: list[dict[str, Any]] = []

    for raw_skill, raw_level in (responses or {}).items():
        skill = normalise_skill(str(raw_skill))
        if not skill:
            continue
        level = max(0, min(MAX_PROFICIENCY, int(raw_level or 0)))
        if level < CLAIM_THRESHOLD:
            adjusted[skill] = level
            continue

        supported = skill in evidence or any(
            skill in term or term in skill for term in evidence
        )
        if not supported and is_soft_skill(skill):
            supported = has_activity
        if supported:
            adjusted[skill] = level
            continue

        adjusted[skill] = UNSUPPORTED_CEILING
        adjustments.append(
            {
                "skill": skill,
                "claimed": level,
                "recorded": UNSUPPORTED_CEILING,
                "reason": (
                    "add a role, project or volunteering entry that shows this"
                    if is_soft_skill(skill)
                    else "no supporting project, certificate or experience in your profile"
                ),
            }
        )

    return adjusted, adjustments


def analyse(
    *,
    domain: str,
    responses: dict[str, int],
    demand_rows: Iterable[dict[str, Any]],
    profile: Any = None,
) -> AssessmentResult:
    """Score an assessment into strengths, gaps and a readiness figure."""
    corroborated, adjustments = corroborate(responses, profile=profile)

    demand_by_skill: dict[str, dict[str, Any]] = {}
    for row in demand_rows or []:
        skill = normalise_skill(str(row.get("skill") or ""))
        if skill:
            demand_by_skill[skill] = row

    strengths: list[SkillGap] = []
    gaps: list[SkillGap] = []
    weighted_total = 0.0
    weighted_have = 0.0
    adjusted_skills = {entry["skill"] for entry in adjustments}

    for skill, row in demand_by_skill.items():
        share = float(row.get("share") or 0.0)
        level = int(corroborated.get(skill, 0))
        soft = bool(row.get("is_soft", is_soft_skill(skill)))

        # Readiness is demand-weighted: being strong at what this domain
        # actually asks for counts for more than breadth across everything.
        weighted_total += share * MAX_PROFICIENCY
        weighted_have += share * level

        deficit = MAX_PROFICIENCY - level
        entry = SkillGap(
            skill=skill,
            level=level,
            demand_share=share,
            is_soft=soft,
            priority=round(share * deficit, 6),
            corroborated=skill not in adjusted_skills,
        )
        if level >= CLAIM_THRESHOLD:
            strengths.append(entry)
        elif deficit > 0:
            gaps.append(entry)

    strengths.sort(key=lambda item: (-item.demand_share, item.skill))
    gaps.sort(key=lambda item: (-item.priority, item.skill))

    readiness = 0.0
    if weighted_total > 0:
        readiness = round(100.0 * weighted_have / weighted_total, 1)

    return AssessmentResult(
        domain=domain,
        responses={normalise_skill(k) or k: v for k, v in (responses or {}).items()},
        corroborated=corroborated,
        strengths=strengths,
        gaps=gaps,
        readiness_score=max(0.0, min(100.0, readiness)),
        adjustments=adjustments,
    )
