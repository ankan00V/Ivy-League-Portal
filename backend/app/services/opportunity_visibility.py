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


def canonical_opportunity_type(value: str | None) -> str | None:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    mapping = {
        "hiring challenge": "Hiring Challenge",
        "internship": "Internship",
        "job": "Job",
        "competition": "Competition",
        "hackathon": "Hackathon",
    }
    return mapping.get(candidate, " ".join(part.capitalize() for part in candidate.split()))


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
    lifecycle = str(getattr(opportunity, "lifecycle_status", "published") or "published").strip().lower()
    if lifecycle != "published":
        return False
    if is_opportunity_expired(opportunity, now=now):
        return False
    return is_trust_visible(opportunity)
