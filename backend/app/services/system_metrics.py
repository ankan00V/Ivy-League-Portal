from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core.metrics import OPPORTUNITY_FRESHNESS_SECONDS, OPPORTUNITY_STALE
from app.models.opportunity import Opportunity


async def refresh_freshness_metrics() -> dict[str, float | bool]:
    """
    Updates Prometheus gauges for opportunity freshness.

    Freshness is computed as seconds since the latest opportunity last_seen_at/updated_at/created_at.
    """
    now = datetime.utcnow()
    latest = await Opportunity.find_many().sort("-last_seen_at").limit(1).to_list()
    if not latest:
        if OPPORTUNITY_FRESHNESS_SECONDS is not None:
            OPPORTUNITY_FRESHNESS_SECONDS.set(0.0)
        if OPPORTUNITY_STALE is not None:
            OPPORTUNITY_STALE.set(0.0)
        return {"freshness_seconds": 0.0, "stale": False}

    item = latest[0]
    last = item.last_seen_at or item.updated_at or item.created_at
    last_value = last if last is not None else now
    freshness_seconds = max(0.0, (now - last_value).total_seconds())
    stale_threshold_seconds = max(60.0, float(max(1, settings.SCRAPER_MAX_STALENESS_MINUTES)) * 60.0)
    stale = freshness_seconds > stale_threshold_seconds

    if OPPORTUNITY_FRESHNESS_SECONDS is not None:
        OPPORTUNITY_FRESHNESS_SECONDS.set(float(freshness_seconds))
    if OPPORTUNITY_STALE is not None:
        OPPORTUNITY_STALE.set(1.0 if stale else 0.0)

    return {"freshness_seconds": float(freshness_seconds), "stale": bool(stale)}

