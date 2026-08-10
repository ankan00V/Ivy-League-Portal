"""No private ceilings on the feed path.

The visible feed was capped three separate times by three different constants:
_load_active_opportunities at 200, get_personalized_recommendations at 50, and
recommendation_service.rank slicing to 50 at the very end. Each was invisible
from the others, so raising one changed nothing and the feed still looked like
the scrapers had stalled. One setting now governs the whole path.

Search, shortlist and history endpoints keep their own smaller limits on
purpose - a "smart shortlist" of 600 would not be a shortlist.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py"
RANKER = BACKEND_ROOT / "app" / "services" / "recommendation_service.py"


def _function_body(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    nxt = source.find("\nasync def ", start + 1)
    alt = source.find("\ndef ", start + 1)
    end = min(x for x in (nxt, alt, len(source)) if x != -1)
    return source[start:end]


class TestNoPrivateFeedCeilings:
    def test_personalised_endpoint_uses_the_shared_ceiling(self):
        body = _function_body(ENDPOINT, "get_personalized_recommendations")
        assert "settings.OPPORTUNITY_FEED_MAX_LIMIT" in body
        assert "min(limit, 50)" not in body

    def test_ranker_does_not_re_clamp_what_the_caller_asked_for(self):
        """rank() truncating to 50 made the endpoint's limit meaningless."""
        source = RANKER.read_text(encoding="utf-8")
        assert "min(limit, 50)" not in source, (
            "the ranker must not silently discard the caller's limit"
        )
        assert "settings.OPPORTUNITY_FEED_MAX_LIMIT" in source

    def test_feed_candidate_and_unified_feed_share_the_ceiling(self):
        for name in ("_retrieve_feed_candidates", "get_unified_feed"):
            body = _function_body(ENDPOINT, name)
            assert "settings.OPPORTUNITY_FEED_MAX_LIMIT" in body, name
            assert "min(int(limit), 50)" not in body, name

    def test_search_and_shortlist_keep_their_smaller_limits(self):
        """Deliberately not raised - these are not the feed."""
        for name in ("semantic_search_opportunities", "get_smart_shortlist"):
            body = _function_body(ENDPOINT, name)
            assert re.search(r"min\((?:int\()?limit\)?, 50\)", body), (
                f"{name} should stay bounded; a shortlist of hundreds is not a shortlist"
            )

    def test_ceiling_still_exceeds_the_corpus(self):
        assert settings.OPPORTUNITY_FEED_MAX_LIMIT >= 600
