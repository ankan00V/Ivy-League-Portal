"""How scarce a skill is in the candidate pool, for the people hiring for it.

A recruiter can already see how many people applied. What no job board tells
them is whether the skill they are asking for exists in the market they are
fishing in - so a listing sits open for six weeks and nobody can say whether the
salary is wrong, the description is wrong, or the skill is simply rare.

The two datasets to answer that were already here. The demand table says how
often a skill appears across live postings, which is competition. Candidate
assessments say how many people can evidence it, which is supply. A skill with
high demand and low supply is one a recruiter should either pay for, train for,
or stop requiring - and that is a decision, where "12 applicants" is only a
number.

The privacy shape matters as much as the arithmetic. This is one employer being
told about other people's students, so it reports proportions over a pool that
must be large enough to hide anyone in it, and it never returns a candidate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: Assessed candidates needed before any supply figure is reported. Smaller than
#: a cohort floor because this exposes no institution and no individual, only a
#: market-wide proportion - but not so small that one person moves it visibly.
MIN_POOL_FOR_SUPPLY = 5

#: Level at or above which a candidate is counted as having the skill. Same
#: threshold the assessment itself uses for "confident", so a recruiter and a
#: student are never looking at two different definitions of the same word.
SUPPLY_THRESHOLD = 3


@dataclass
class SkillScarcity:
    skill: str
    #: Share of live postings asking for it. High means you are competing.
    demand_share: float
    #: Share of assessed candidates who can evidence it. Low means they are rare.
    supply: float
    candidates_assessed: int
    candidates_with_skill: int
    is_soft: bool
    #: demand minus supply. The higher this is, the harder this hire will be.
    scarcity: float

    @property
    def verdict(self) -> str:
        if self.supply >= 0.6:
            return "widely available"
        if self.supply >= 0.3:
            return "competitive"
        return "scarce"


def build_scarcity(
    *,
    demand_rows: Iterable[dict[str, Any]],
    candidate_levels: Iterable[dict[str, Any]],
    limit: int = 12,
    min_pool: int = MIN_POOL_FOR_SUPPLY,
) -> tuple[list[SkillScarcity], Optional[str]]:
    """Cross what employers ask for against what candidates can evidence.

    Returns (rows, refusal). A refusal rather than an empty list, because "no
    data yet" and "no scarce skills" are opposite findings and a recruiter
    acting on the wrong one wastes a hiring quarter.
    """
    pool = [dict(entry or {}) for entry in candidate_levels]
    if len(pool) < max(1, int(min_pool)):
        return [], (
            f"{len(pool)} candidates have completed a skill assessment. "
            f"At least {min_pool} are needed before supply figures mean anything - "
            "below that one person moves every percentage on this page."
        )

    rows: list[SkillScarcity] = []
    for row in demand_rows or []:
        skill = str(row.get("skill") or "").strip().lower()
        if not skill:
            continue
        # Only candidates actually asked about this skill count. Questionnaires
        # are generated per domain, so two candidates need not share a list, and
        # treating silence as absence would report every skill as scarce.
        asked = [levels for levels in pool if skill in levels]
        if len(asked) < max(1, int(min_pool)):
            continue
        have = sum(1 for levels in asked if int(levels.get(skill) or 0) >= SUPPLY_THRESHOLD)
        supply = have / len(asked)
        share = float(row.get("share") or 0.0)
        rows.append(
            SkillScarcity(
                skill=skill,
                demand_share=round(share, 4),
                supply=round(supply, 4),
                candidates_assessed=len(asked),
                candidates_with_skill=have,
                is_soft=bool(row.get("is_soft", False)),
                scarcity=round(share - supply, 4),
            )
        )

    rows.sort(key=lambda item: (-item.scarcity, -item.demand_share))
    return rows[: max(1, int(limit))], None


@dataclass
class ListingPerformance:
    opportunity_id: str
    title: str
    status: str
    applications: int
    shortlisted: int
    #: None rather than 0 when nobody has applied. A shortlist rate of "0%" on a
    #: listing with no applicants describes the applicants, not the listing.
    shortlist_rate: Optional[float]
    days_open: Optional[int]


def summarise_listings(rows: Iterable[dict[str, Any]], *, limit: int = 10) -> list[ListingPerformance]:
    """Per-listing performance, worst-performing first.

    Ordered by applications ascending rather than descending: a recruiter opens
    this page to find the listing that is not working, not to admire the one
    that is.
    """
    listings = [
        ListingPerformance(
            opportunity_id=str(row.get("opportunity_id") or ""),
            title=str(row.get("title") or ""),
            status=str(row.get("status") or "draft"),
            applications=int(row.get("applications") or 0),
            shortlisted=int(row.get("shortlisted") or 0),
            shortlist_rate=(
                round(int(row.get("shortlisted") or 0) / int(row.get("applications") or 0), 4)
                if int(row.get("applications") or 0) > 0
                else None
            ),
            days_open=row.get("days_open"),
        )
        for row in rows or []
    ]
    listings.sort(key=lambda item: (item.applications, item.title))
    return listings[: max(1, int(limit))]
