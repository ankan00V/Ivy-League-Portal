from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.services.scraper import is_opportunity_active
from app.services.opportunity_trust import is_trust_visible

OpportunityPortal = Literal["career", "competitive", "other"]

CAREER_TYPES = {"hiring challenge", "internship", "job"}
COMPETITIVE_TYPES = {"competition", "hackathon"}

CAREER_KEYWORDS = {
    "hiring challenge",
    "internship",
    "intern",
    "job",
    "hiring",
    "developer",
    "engineer",
    "lead",
}
COMPETITIVE_KEYWORDS = {
    "hackathon",
    "competition",
    "challenge",
    "quiz",
    "conference",
    "workshop",
    "bootcamp",
    "webinar",
    "buildathon",
    "ctf",
}


_CANONICAL_OPPORTUNITY_TYPES = {
    "hiring challenge": "Hiring Challenge",
    "hiring challenges": "Hiring Challenge",
    "internship": "Internship",
    "internships": "Internship",
    "job": "Job",
    "jobs": "Job",
    "competition": "Competition",
    "competitions": "Competition",
    "hackathon": "Hackathon",
    "hackathons": "Hackathon",
    "scholarship": "Scholarship",
    "scholarships": "Scholarship",
    "conference": "Conference",
    "conferences": "Conference",
    "workshop": "Workshop",
    "workshops": "Workshop",
    "fellowship": "Fellowship",
    "fellowships": "Fellowship",
    "research": "Research",
    "opportunity": "Opportunity",
    "opportunities": "Opportunity",
}


def canonical_opportunity_type(value: str | None) -> str | None:
    """Normalise an opportunity type to a single canonical spelling.

    Plurals previously fell through to the generic title-caser, so the corpus
    carried "Hackathon" and "Hackathons" as separate types (31 and 18 rows) and
    "Conference"/"Conferences" likewise. Type filters and portal routing treat
    them as distinct, so a student filtering hackathons saw roughly half of
    them.
    """
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    mapped = _CANONICAL_OPPORTUNITY_TYPES.get(candidate)
    if mapped:
        return mapped
    # Fall back to singularising a simple trailing plural before title-casing,
    # so an unmapped "Symposiums" does not diverge from "Symposium".
    if candidate.endswith("s") and candidate[:-1] in _CANONICAL_OPPORTUNITY_TYPES:
        return _CANONICAL_OPPORTUNITY_TYPES[candidate[:-1]]
    return " ".join(part.capitalize() for part in candidate.split())


def resolve_opportunity_portal(
    *,
    opportunity_type: str | None,
    title: str | None = None,
    description: str | None = None,
    portal_category: str | None = None,
) -> OpportunityPortal:
    explicit_portal = str(portal_category or "").strip().lower()
    if explicit_portal in {"career", "competitive", "other"}:
        return explicit_portal  # type: ignore[return-value]

    normalized_type = str(opportunity_type or "").strip().lower()
    if normalized_type in CAREER_TYPES:
        return "career"
    if normalized_type in COMPETITIVE_TYPES:
        return "competitive"

    haystack = " ".join(
        part for part in [normalized_type, str(title or "").strip().lower(), str(description or "").strip().lower()] if part
    )
    if any(keyword in haystack for keyword in CAREER_KEYWORDS):
        return "career"
    if any(keyword in haystack for keyword in COMPETITIVE_KEYWORDS):
        return "competitive"
    return "other"


def is_opportunity_expired(opportunity: Any, *, now: datetime | None = None) -> bool:
    return not is_opportunity_active(opportunity, now=now)


def is_student_visible_opportunity(opportunity: Any, *, now: datetime | None = None) -> bool:
    status = str(getattr(opportunity, "opportunity_status", "active") or "active").strip().lower()
    if status in {"expired", "filled", "removed"}:
        return False
    lifecycle = str(getattr(opportunity, "lifecycle_status", "published") or "published").strip().lower()
    if lifecycle != "published":
        return False
    if is_opportunity_expired(opportunity, now=now):
        return False
    return is_trust_visible(opportunity)
