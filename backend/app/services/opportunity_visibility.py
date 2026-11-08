from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from app.services.scraper import is_opportunity_active
from app.services.opportunity_trust import is_trust_visible
from app.services.feed_policy import canonical_type, listing_rejection_reason, resolve_portal
from app.core.config import settings

OpportunityPortal = Literal["career", "competitive", "other"]

def canonical_opportunity_type(value: str | None) -> str | None:
    """Normalise an opportunity type to a single canonical spelling.

    Plurals previously fell through to the generic title-caser, so the corpus
    carried "Hackathon" and "Hackathons" as separate types (31 and 18 rows) and
    "Conference"/"Conferences" likewise. Type filters and portal routing treat
    them as distinct, so a student filtering hackathons saw roughly half of
    them.
    """
    return canonical_type(value)


def resolve_opportunity_portal(
    *,
    opportunity_type: str | None,
    title: str | None = None,
    description: str | None = None,
    portal_category: str | None = None,
) -> OpportunityPortal:
    return cast(OpportunityPortal, resolve_portal(opportunity_type, title, portal_category))


def is_opportunity_expired(opportunity: Any, *, now: datetime | None = None) -> bool:
    return not is_opportunity_active(opportunity, now=now)


def is_student_visible_opportunity(opportunity: Any, *, now: datetime | None = None) -> bool:
    if hasattr(opportunity, "title") or hasattr(opportunity, "url"):
        record = {field: getattr(opportunity, field, None) for field in (
            "title", "url", "source", "opportunity_type", "url_liveness_status",
        )}
        if listing_rejection_reason(record, allowed_types=settings.OPPORTUNITY_SCOPE_TYPES):
            return False
    status = str(getattr(opportunity, "opportunity_status", "active") or "active").strip().lower()
    if status in {"expired", "filled", "removed"}:
        return False
    lifecycle = str(getattr(opportunity, "lifecycle_status", "published") or "published").strip().lower()
    if lifecycle != "published":
        return False
    if is_opportunity_expired(opportunity, now=now):
        return False
    return is_trust_visible(opportunity)
