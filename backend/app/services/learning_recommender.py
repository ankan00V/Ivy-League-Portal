"""Match learning programmes to the gaps a student actually has.

The problem statement wants "personalized learning recommendations" and
"skill development programs aligned with industry requirements". Both halves
matter, and only one of them is hard.

Aligning a programme to industry is already solved: the demand table says what
employers are asking for, and the assessment says which of those the student
cannot yet evidence. Personalising is the part that goes wrong quietly. A
recommender that ranks by how many skills a programme lists will always favour
the programme claiming to teach twenty things, and a student who follows that
advice spends a semester on the broadest advert rather than their largest gap.

So a programme is scored by the gaps it closes, weighted by what those gaps are
worth - the same demand-times-deficit priority the assessment already computed -
and divided by nothing. Breadth is not a virtue here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProgramMatch:
    program_id: str
    title: str
    provider: str
    url: Optional[str]
    program_format: str
    duration_weeks: Optional[int]
    is_free: bool
    certificate_offered: bool
    #: The student's own gaps this programme addresses, highest value first.
    closes_gaps: list[str]
    #: Summed priority of those gaps. Comparable across programmes.
    score: float


def _gap_priorities(gaps: Iterable[dict[str, Any]]) -> dict[str, float]:
    priorities: dict[str, float] = {}
    for gap in gaps or []:
        skill = " ".join(str(gap.get("skill") or "").split()).lower()
        if not skill:
            continue
        try:
            priority = float(gap.get("priority") or 0.0)
        except (TypeError, ValueError):
            continue
        # A gap listed twice should not count twice.
        priorities[skill] = max(priorities.get(skill, 0.0), priority)
    return priorities


def recommend_programs(
    *,
    gaps: Iterable[dict[str, Any]],
    programs: Iterable[Any],
    limit: int = 10,
) -> list[ProgramMatch]:
    """Rank programmes by the value of the gaps they close.

    Programmes that close none of this student's gaps are dropped rather than
    ranked last. A recommendation list padded to a fixed length with irrelevant
    entries teaches the student that the list is not worth reading.
    """
    priorities = _gap_priorities(gaps)
    if not priorities:
        return []

    matches: list[ProgramMatch] = []
    for program in programs or []:
        taught = {
            " ".join(str(skill or "").split()).lower()
            for skill in (getattr(program, "skills_taught", None) or [])
        }
        overlap = [skill for skill in taught if skill in priorities]
        if not overlap:
            continue
        overlap.sort(key=lambda skill: -priorities[skill])
        score = round(sum(priorities[skill] for skill in overlap), 6)
        matches.append(
            ProgramMatch(
                program_id=str(getattr(program, "id", "")),
                title=str(getattr(program, "title", "")),
                provider=str(getattr(program, "provider", "")),
                url=getattr(program, "url", None),
                program_format=str(getattr(program, "program_format", "course")),
                duration_weeks=getattr(program, "duration_weeks", None),
                is_free=bool(getattr(program, "is_free", True)),
                certificate_offered=bool(getattr(program, "certificate_offered", False)),
                closes_gaps=overlap,
                score=score,
            )
        )

    # Ties broken towards free programmes, then shorter ones: between two
    # equally useful options the cheaper and quicker one is the better advice.
    matches.sort(
        key=lambda match: (
            -match.score,
            not match.is_free,
            match.duration_weeks if match.duration_weeks is not None else 9999,
            match.title,
        )
    )
    return matches[: max(1, int(limit))]
