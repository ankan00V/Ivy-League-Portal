"""What industry is asking for, against what a cohort can actually do.

This is the one thing on this platform that no job board can produce, and it is
the problem statement's actual ask - "align teaching with current industry
practices". Two datasets already exist and had never been crossed:

  * the demand table, derived from live postings, which says what employers are
    advertising for right now and how often;
  * cohort assessments, which say which of those skills students can evidence.

Crossing them turns two lists into a decision. "Docker appears in 18% of live
postings in your domain and 7% of your students can evidence it" is a curriculum
argument. Either number alone is trivia.

Two design choices worth stating.

Coverage is measured against students who took the assessment, not against the
whole cohort. A student who never answered is not evidence of absence, and
counting them as a gap would make every institution look worse the more students
it enrolled.

And a skill is only reported when enough students have been assessed on it to
mean anything. Below that the percentage is noise with a decimal point, and a
department would be asked to change a syllabus on the strength of two answers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: Assessed students needed before a skill's coverage is reported at all.
MIN_ASSESSED_FOR_COVERAGE = 3

#: Level at or above which a student is treated as having the skill. Matches the
#: assessment's own "confident" threshold, so the two never disagree on screen.
COVERAGE_THRESHOLD = 3


@dataclass
class SkillSignal:
    skill: str
    #: Share of live postings naming it, 0..1.
    demand_share: float
    #: Share of assessed students who can evidence it, 0..1.
    coverage: float
    students_assessed: int
    students_covered: int
    is_soft: bool
    #: demand minus coverage. Positive means industry wants it more than the
    #: cohort has it - the gap worth teaching into. Negative means the cohort is
    #: ahead of local demand, which is not a problem but is worth seeing.
    gap: float


def build_signal(
    *,
    demand_rows: Iterable[dict[str, Any]],
    assessments: Iterable[dict[str, Any]],
    limit: int = 15,
    min_assessed: int = MIN_ASSESSED_FOR_COVERAGE,
) -> list[SkillSignal]:
    """Cross demand against cohort coverage, most actionable gap first.

    `assessments` are the per-student corroborated level maps, not their raw
    answers: a claim the profile could not support must not count as coverage,
    or the institution is shown its students' confidence rather than their
    ability.
    """
    levels_by_student = [dict(entry or {}) for entry in assessments]
    assessed_total = len(levels_by_student)

    signals: list[SkillSignal] = []
    for row in demand_rows or []:
        skill = str(row.get("skill") or "").strip().lower()
        if not skill:
            continue
        share = float(row.get("share") or 0.0)

        # Only students who were actually asked about this skill count as
        # assessed on it. A questionnaire is generated per domain and shifts as
        # the corpus moves, so two students may not have answered the same list.
        asked = [levels for levels in levels_by_student if skill in levels]
        if len(asked) < max(1, int(min_assessed)):
            continue
        covered = sum(1 for levels in asked if int(levels.get(skill) or 0) >= COVERAGE_THRESHOLD)
        coverage = covered / len(asked)

        signals.append(
            SkillSignal(
                skill=skill,
                demand_share=round(share, 4),
                coverage=round(coverage, 4),
                students_assessed=len(asked),
                students_covered=covered,
                is_soft=bool(row.get("is_soft", False)),
                gap=round(share - coverage, 4),
            )
        )

    # Ranked by how much demand outstrips coverage, then by demand. A skill
    # nobody advertises is not a curriculum priority however few students have
    # it, which is the mistake a coverage-only ranking makes.
    signals.sort(key=lambda item: (-item.gap, -item.demand_share))
    return signals[: max(1, int(limit))]


@dataclass
class FunnelStage:
    label: str
    count: int
    #: Share of the stage before it, so a drop-off is visible rather than
    #: inferred from two absolute numbers.
    conversion_from_previous: Optional[float]


def build_funnel(
    *,
    cohort_size: int,
    profiles_complete: int,
    assessments_taken: int,
    students_with_applications: int,
) -> list[FunnelStage]:
    """Where a cohort stops progressing.

    An institution asking "why is placement low" needs to know whether students
    are failing to get offers or never finishing a profile, and those have
    completely different remedies.
    """
    raw = [
        ("Registered", max(0, int(cohort_size))),
        ("Profile complete", max(0, int(profiles_complete))),
        ("Skills assessed", max(0, int(assessments_taken))),
        ("Applied to something", max(0, int(students_with_applications))),
    ]
    stages: list[FunnelStage] = []
    previous: Optional[int] = None
    for label, count in raw:
        conversion = None
        # Only report a conversion where this stage is genuinely a subset of the
        # one before. Applying does not require having been assessed, so with 2
        # assessed and 3 applied the naive ratio reads 150% - a number that is
        # not wrong so much as meaningless, and which invites an institution to
        # explain a drop-off that never happened. Where the stages are not
        # nested the count still shows; only the false ratio is withheld.
        if previous is not None and previous > 0 and count <= previous:
            conversion = round(count / previous, 4)
        stages.append(FunnelStage(label=label, count=count, conversion_from_previous=conversion))
        previous = count
    return stages
