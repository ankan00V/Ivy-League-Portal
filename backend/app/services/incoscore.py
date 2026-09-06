"""InCoScore: an evidence-weighted competency score.

The previous formula counted strings. Nine words typed into "skills" earned the
full 35 points, education and resume were 10 points each for any non-empty
value, and everyone started at 10 - so three users with zero achievements
between them all sat at 95.0 and the leaderboard could not separate them.

Three changes make it discriminate:

  Evidence tiers. A skill nobody can corroborate is worth roughly half of one
  that also appears in the student's projects, certificates or experience. Self
  declaration alone can no longer reach the top band.

  Diminishing returns. Each component uses 1 - exp(-n/k) rather than a linear
  ramp into a clamp, so the third item matters more than the fifteenth and
  padding a list stops paying.

  Recency. Evidence decays if the profile has not been touched in months, so a
  score reflects a student as they are now rather than as they once were.

Outcomes (applications sent, replies received) are a bounded uplift on top,
never a deduction: a first-year with nothing applied for yet is not punished for
it, while a student actually using the platform can climb past someone who only
filled in a form.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.time import as_utc_aware, utc_now

# Component ceilings. They sum to 90; outcomes contribute the last 10, so a
# complete, corroborated profile is a strong score without requiring the student
# to have applied for anything yet.
MAX_ACADEMIC = 15.0
MAX_SKILLS = 25.0
MAX_EVIDENCE = 25.0
MAX_RESUME = 10.0
MAX_DIRECTION = 10.0
MAX_NARRATIVE = 5.0
MAX_OUTCOMES = 10.0

# Weight applied to a skill nobody can corroborate. Not zero - claiming a skill
# is weak evidence, but it is evidence - and deliberately well under half, so a
# long unsupported list cannot out-score a short demonstrated one.
UNCORROBORATED_WEIGHT = 0.45

_SPLIT = re.compile(r"[,;\n|/]+")
_WORD = re.compile(r"[a-z0-9+#.]{2,}")


@dataclass(frozen=True)
class OutcomeSignals:
    """What the student has actually done, not what they claim."""

    applications: int = 0
    responses: int = 0          # shortlisted / interview / offer
    active_days: int = 0        # distinct days with a logged interaction


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-component detail, so a score can be explained rather than asserted."""

    academic: float
    skills: float
    evidence: float
    resume: float
    direction: float
    narrative: float
    outcomes: float
    recency_multiplier: float
    total: float

    def as_dict(self) -> dict[str, float]:
        return {
            "academic": round(self.academic, 2),
            "skills": round(self.skills, 2),
            "evidence": round(self.evidence, 2),
            "resume": round(self.resume, 2),
            "direction": round(self.direction, 2),
            "narrative": round(self.narrative, 2),
            "outcomes": round(self.outcomes, 2),
            "recency_multiplier": round(self.recency_multiplier, 3),
            "total": round(self.total, 2),
        }


def _items(value: Any) -> list[str]:
    """Split a free-text or list field into cleaned, de-duplicated entries."""
    if value is None:
        return []
    raw: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw = [str(v) for v in value]
    else:
        raw = _SPLIT.split(str(value))
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        cleaned = item.strip().lower()
        # One-character "skills" are noise, not competencies.
        if len(cleaned) < 2 or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _saturating(count: float, ceiling: float, k: float) -> float:
    """ceiling * (1 - e^(-count/k)); the k-th item is worth ~63% of the ceiling."""
    if count <= 0:
        return 0.0
    return ceiling * (1.0 - math.exp(-float(count) / float(k)))


def _substantive(value: Any, min_chars: int = 40) -> bool:
    """Whether a free-text field carries real content rather than a placeholder.

    Length is a blunt proxy, but it separates "x" and "n/a" - which used to earn
    a full 10 points for education - from an actual description.
    """
    text = str(value or "").strip()
    return len(text) >= min_chars


def _corpus(profile: Any) -> set[str]:
    """Words the student has written anywhere that could corroborate a skill."""
    parts = [
        getattr(profile, "projects", "") or "",
        getattr(profile, "certificates", "") or "",
        getattr(profile, "achievements", "") or "",
        getattr(profile, "responsibilities", "") or "",
        getattr(profile, "experience_summary", "") or "",
        getattr(profile, "bio", "") or "",
        getattr(profile, "current_job_role", "") or "",
        getattr(profile, "education", "") or "",
    ]
    return set(_WORD.findall(" ".join(parts).lower()))


def _academic_score(profile: Any) -> float:
    """Verifiable academic identity, graded rather than a single binary flag."""
    points = 0.0
    if str(getattr(profile, "college_name", "") or "").strip():
        points += 5.0
    if str(getattr(profile, "course", "") or "").strip():
        points += 3.0
    if str(getattr(profile, "course_specialization", "") or "").strip():
        points += 2.0
    if getattr(profile, "passout_year", None) or getattr(profile, "graduation_year", None):
        points += 3.0
    if str(getattr(profile, "user_type", "") or "").strip():
        points += 2.0
    return min(MAX_ACADEMIC, points)


def _skill_score(profile: Any) -> float:
    """Skills weighted by whether anything else in the profile backs them up."""
    skills = _items(getattr(profile, "skills", None))
    if not skills:
        return 0.0
    corpus = _corpus(profile)
    effective = 0.0
    for skill in skills:
        tokens = set(_WORD.findall(skill))
        corroborated = bool(tokens) and tokens.issubset(corpus)
        effective += 1.0 if corroborated else UNCORROBORATED_WEIGHT
    return _saturating(effective, MAX_SKILLS, k=6.0)


def _evidence_score(profile: Any) -> float:
    """Things the student has actually produced, weighted by kind.

    Certificates and projects outrank a line in an achievements list because
    they are the ones an employer could go and check.
    """
    weights = (
        ("projects", 1.0),
        ("certificates", 1.0),
        ("achievements", 0.7),
        ("responsibilities", 0.6),
        ("experience_summary", 0.8),
    )
    effective = 0.0
    for field, weight in weights:
        value = getattr(profile, field, None)
        entries = _items(value)
        if not entries:
            continue
        # A field holding one long paragraph counts as one substantive entry;
        # a list of five counts as five, but each must clear the noise floor.
        substantive = [e for e in entries if len(e) >= 8]
        effective += weight * len(substantive)
        if _substantive(value, min_chars=120):
            effective += weight  # depth bonus for a genuinely detailed entry
    return _saturating(effective, MAX_EVIDENCE, k=5.0)


def _resume_score(profile: Any, now: datetime) -> float:
    """Present and current. A resume from two years ago is not evidence of now."""
    has_resume = bool(str(getattr(profile, "resume_url", "") or "").strip())
    if not has_resume:
        return 0.0
    points = 4.0
    uploaded = as_utc_aware(getattr(profile, "resume_uploaded_at", None))
    if uploaded:
        age_days = max(0.0, (now - uploaded).total_seconds() / 86400.0)
        if age_days <= 180:
            points += 6.0
        elif age_days <= 365:
            points += 4.0
        elif age_days <= 730:
            points += 2.0
    return min(MAX_RESUME, points)


def _direction_score(profile: Any) -> float:
    """Whether the student has told us what they are actually looking for."""
    count = 0.0
    for field in ("career_intent", "goals", "domains_of_interest", "opportunity_types"):
        count += len(_items(getattr(profile, field, None)))
    for field in ("preferred_roles", "preferred_work_mode", "preferred_locations"):
        if str(getattr(profile, field, "") or "").strip():
            count += 1.0
    return _saturating(count, MAX_DIRECTION, k=4.0)


def _narrative_score(profile: Any) -> float:
    """A written bio, judged on substance rather than presence."""
    bio = getattr(profile, "bio", None)
    if _substantive(bio, min_chars=200):
        return MAX_NARRATIVE
    if _substantive(bio, min_chars=80):
        return MAX_NARRATIVE * 0.6
    if _substantive(bio, min_chars=30):
        return MAX_NARRATIVE * 0.3
    return 0.0


def _outcome_score(outcomes: Optional[OutcomeSignals]) -> float:
    """Bounded uplift for real activity. Additive only - never a penalty."""
    if not outcomes:
        return 0.0
    applied = _saturating(outcomes.applications, 5.0, k=4.0)
    replied = _saturating(outcomes.responses, 4.0, k=2.0)
    engaged = _saturating(outcomes.active_days, 1.0, k=6.0)
    return min(MAX_OUTCOMES, applied + replied + engaged)


def _recency_multiplier(profile: Any, now: datetime) -> float:
    """Decay stale profiles, gently and with a floor.

    Capped at a 15% reduction: staleness should nudge a ranking, not erase a
    student's record because they took a semester off.
    """
    updated = as_utc_aware(getattr(profile, "updated_at", None)) or as_utc_aware(
        getattr(profile, "created_at", None)
    )
    if not updated:
        return 1.0
    months = max(0.0, (now - updated).total_seconds() / (86400.0 * 30.0))
    if months <= 6:
        return 1.0
    return max(0.85, 1.0 - (months - 6.0) * 0.0125)


def score_profile(
    profile: Any,
    outcomes: Optional[OutcomeSignals] = None,
    *,
    now: Optional[datetime] = None,
) -> ScoreBreakdown:
    """Full breakdown for one profile."""
    moment = now or utc_now()
    academic = _academic_score(profile)
    skills = _skill_score(profile)
    evidence = _evidence_score(profile)
    resume = _resume_score(profile, moment)
    direction = _direction_score(profile)
    narrative = _narrative_score(profile)
    decay = _recency_multiplier(profile, moment)

    # Decay applies to claimed evidence, not to demonstrated outcomes: an
    # application you actually sent last year still happened.
    base = (academic + skills + evidence + resume + direction + narrative) * decay
    outcome_points = _outcome_score(outcomes)
    total = max(0.0, min(100.0, base + outcome_points))

    return ScoreBreakdown(
        academic=academic,
        skills=skills,
        evidence=evidence,
        resume=resume,
        direction=direction,
        narrative=narrative,
        outcomes=outcome_points,
        recency_multiplier=decay,
        total=round(total, 2),
    )


# Below this many scored profiles a percentile is theatre - with five users,
# "top 20%" is one person - so both the leaderboard and the dashboard fall back
# to the band instead of quoting one.
MIN_COHORT_FOR_PERCENTILE = 20


def percentile_of(score: float, cohort: list[float]) -> Optional[float]:
    """Where a score sits in the live cohort, or None when the cohort is too small.

    Below the threshold a percentile is theatre - with five users, "top 20%" is
    one person - so callers fall back to the absolute band instead.
    """
    values = [float(v) for v in cohort if v is not None]
    if len(values) < MIN_COHORT_FOR_PERCENTILE:
        return None
    below = sum(1 for v in values if v < score)
    return round(100.0 * below / len(values), 1)


def band_for(score: float) -> str:
    """Human-readable band, used wherever a percentile is not yet meaningful."""
    if score >= 85:
        return "Exceptional"
    if score >= 70:
        return "Strong"
    if score >= 55:
        return "Developing"
    if score >= 35:
        return "Emerging"
    return "Getting started"


async def gather_outcomes(user_id: Any) -> OutcomeSignals:
    """Read what the student has actually done.

    Failures here return empty signals rather than raising: outcomes are an
    uplift, so losing them costs a few points, while letting the exception
    escape would fail the whole profile save.
    """
    try:
        from app.models.application import Application
        from app.models.opportunity_interaction import OpportunityInteraction

        applications = await Application.find_many(Application.user_id == user_id).to_list()
        responded = sum(
            1
            for a in applications
            if str(getattr(a, "pipeline_state", "") or "").lower()
            in {"shortlisted", "interview", "offer", "accepted"}
        )
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.user_id == user_id
        ).limit(2000).to_list()
        days = {
            getattr(i, "created_at", None).date()
            for i in interactions
            if getattr(i, "created_at", None)
        }
        return OutcomeSignals(
            applications=len(applications),
            responses=responded,
            active_days=len(days),
        )
    except Exception:  # pragma: no cover - defensive, see docstring
        return OutcomeSignals()


async def score_profile_with_outcomes(profile: Any) -> ScoreBreakdown:
    """Full score including the activity uplift, for callers that can await."""
    outcomes = await gather_outcomes(getattr(profile, "user_id", None))
    return score_profile(profile, outcomes)
