from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core import metrics as metrics_module
from app.models.opportunity import Opportunity
from app.core.time import as_utc_aware, utc_now


async def refresh_freshness_metrics() -> dict[str, float | bool]:
    """
    Updates Prometheus gauges for opportunity freshness.

    Freshness is computed as seconds since the latest opportunity last_seen_at/updated_at/created_at.
    """
    now = utc_now()
    latest = await Opportunity.find_many().sort("-last_seen_at").limit(1).to_list()
    if not latest:
        if metrics_module.OPPORTUNITY_FRESHNESS_SECONDS is not None:
            metrics_module.OPPORTUNITY_FRESHNESS_SECONDS.set(0.0)
        if metrics_module.OPPORTUNITY_STALE is not None:
            metrics_module.OPPORTUNITY_STALE.set(0.0)
        return {"freshness_seconds": 0.0, "stale": False}

    item = latest[0]
    last = item.last_seen_at or item.updated_at or item.created_at
    # Opportunity timestamps are persisted naive-UTC by the scraper, so they come
    # back from Mongo without a tzinfo. Subtracting those from an aware utc_now()
    # raises TypeError, which previously failed the whole scraper job after the
    # scrape had already succeeded.
    last_value = as_utc_aware(last) or now
    freshness_seconds = max(0.0, (now - last_value).total_seconds())
    stale_threshold_seconds = max(60.0, float(max(1, settings.SCRAPER_MAX_STALENESS_MINUTES)) * 60.0)
    stale = freshness_seconds > stale_threshold_seconds

    if metrics_module.OPPORTUNITY_FRESHNESS_SECONDS is not None:
        metrics_module.OPPORTUNITY_FRESHNESS_SECONDS.set(float(freshness_seconds))
    if metrics_module.OPPORTUNITY_STALE is not None:
        metrics_module.OPPORTUNITY_STALE.set(1.0 if stale else 0.0)

    return {"freshness_seconds": float(freshness_seconds), "stale": bool(stale)}
