"""Cohort matching and aggregation for institution accounts.

Problem statement 26044 asks institutions to "monitor student skill development,
internship participation, and placement progress". That means an account which
reads data about other people, so two things decide whether this is a feature or
a leak: who counts as your cohort, and what you are allowed to see about it.

Cohort matching cannot be a string comparison on college_name. Five accounts in
this database spell one university four ways -

    LOVELY PROFESSIONAL UNIVERSITY, PHAGWARA, PUNJAB
    LOVELY PROFESSIONAL UNIVERSITY
    Lovely Professional University, Phagwara, Punjab
    Lovely Professional University

- so equality would report a cohort of one and call it a complete picture.
Email domain alone is no better: three of those five signed up on gmail. Both
signals are used, normalised.

What an institution may see is capped by cohort size. Aggregates over a handful
of students are not aggregates, they are those students' individual records with
a mean sign on them, and "average readiness" across two people identifies both.
Below the floor the answer is a refusal that says why, not an empty dashboard
that reads as "your students have no data".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: Smallest cohort that may be reported on. Chosen to be visibly conservative
#: rather than statistically minimal: this is other people's students.
MIN_COHORT_SIZE = 5

# Location tails and corporate suffixes that make the same institution look like
# several. Applied after punctuation is stripped.
_NAME_NOISE = (
    "university",
    "institute",
    "college",
    "of",
    "technology",
    "engineering",
    "and",
    "the",
)

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_SPACES = re.compile(r"\s+")


def normalise_institution_name(name: str) -> str:
    """Canonical form of an institution name, for matching only.

    Deliberately lossy: it drops the location tail and common structural words
    so that "Lovely Professional University, Phagwara, Punjab" and "LOVELY
    PROFESSIONAL UNIVERSITY" collapse together. It is never shown to anyone -
    the display name is whatever the institution typed.
    """
    value = str(name or "").strip().lower()
    if not value:
        return ""
    # The location tail is almost always after the first comma.
    value = value.split(",")[0]
    value = _PUNCT.sub(" ", value)
    value = _SPACES.sub(" ", value).strip()
    tokens = [token for token in value.split() if token not in _NAME_NOISE]
    # Stripping structural words is what collapses the four spellings of one
    # university, but it over-strips short names into collisions: "National
    # Institute of Technology" and "National University" both reduce to
    # "national", which would put one institution's students in another's
    # dashboard. Whenever too little distinguishing signal survives, fall back
    # to the full name - a cohort split in two is a visible problem, a cohort
    # merged with a stranger's is a disclosure.
    if len(tokens) < 2:
        return value
    return " ".join(tokens)


def email_domain(email: str) -> str:
    value = str(email or "").strip().lower()
    return value.rsplit("@", 1)[-1] if "@" in value else ""


@dataclass(frozen=True)
class CohortMatch:
    matched: bool
    reason: str


def student_matches_institution(
    *,
    student_email: str,
    student_college: Optional[str],
    institution_domain: str,
    institution_name: str,
) -> CohortMatch:
    """Whether this student belongs to this institution's cohort.

    Either signal is sufficient. Requiring both would drop every student who
    signed up on a personal mailbox, which in this database is the majority.
    """
    domain = email_domain(student_email)
    if institution_domain and domain and domain == institution_domain.strip().lower():
        return CohortMatch(True, "email_domain")

    student_key = normalise_institution_name(student_college or "")
    institution_key = normalise_institution_name(institution_name)
    if student_key and institution_key and student_key == institution_key:
        return CohortMatch(True, "college_name")

    return CohortMatch(False, "no_match")


@dataclass
class CohortAggregate:
    cohort_size: int
    matched_by_domain: int
    matched_by_name: int
    profiles_complete: int
    assessments_taken: int
    average_readiness: Optional[float]
    average_incoscore: Optional[float]
    applications_total: int
    students_with_applications: int
    top_gaps: list[dict[str, Any]]


def summarise_cohort(
    rows: Iterable[dict[str, Any]],
    *,
    min_cohort_size: int = MIN_COHORT_SIZE,
) -> tuple[Optional[CohortAggregate], Optional[str]]:
    """Aggregate a cohort, or refuse and say why.

    Returns (aggregate, refusal). Exactly one is populated. A refusal is not an
    error state to be swallowed into an empty dashboard - "we cannot show this
    yet" and "your students are doing nothing" look identical on screen and mean
    opposite things.
    """
    members = list(rows)
    size = len(members)
    if size < max(1, int(min_cohort_size)):
        return None, (
            f"Cohort has {size} student{'s' if size != 1 else ''}; at least "
            f"{min_cohort_size} are needed before aggregates can be shown "
            "without identifying individuals."
        )

    readiness = [r["readiness"] for r in members if r.get("readiness") is not None]
    incoscores = [r["incoscore"] for r in members if r.get("incoscore") is not None]
    applications = sum(int(r.get("applications") or 0) for r in members)

    gap_weight: dict[str, float] = {}
    gap_students: dict[str, int] = {}
    for member in members:
        for gap in member.get("gaps") or []:
            skill = str(gap.get("skill") or "").strip().lower()
            if not skill:
                continue
            gap_weight[skill] = gap_weight.get(skill, 0.0) + float(gap.get("priority") or 0.0)
            gap_students[skill] = gap_students.get(skill, 0) + 1

    top_gaps = [
        {
            "skill": skill,
            "students_affected": gap_students[skill],
            "weight": round(weight, 4),
        }
        for skill, weight in sorted(gap_weight.items(), key=lambda item: -item[1])
    ][:10]

    aggregate = CohortAggregate(
        cohort_size=size,
        matched_by_domain=sum(1 for r in members if r.get("matched_by") == "email_domain"),
        matched_by_name=sum(1 for r in members if r.get("matched_by") == "college_name"),
        profiles_complete=sum(1 for r in members if r.get("profile_complete")),
        assessments_taken=sum(1 for r in members if r.get("readiness") is not None),
        average_readiness=round(sum(readiness) / len(readiness), 1) if readiness else None,
        average_incoscore=round(sum(incoscores) / len(incoscores), 1) if incoscores else None,
        applications_total=applications,
        students_with_applications=sum(1 for r in members if int(r.get("applications") or 0) > 0),
        top_gaps=top_gaps,
    )
    return aggregate, None
