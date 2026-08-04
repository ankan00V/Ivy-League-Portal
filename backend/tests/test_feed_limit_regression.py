"""The feed must not silently hide most of the corpus.

The active corpus held 743 opportunities while `_load_active_opportunities`
capped every request at a hardcoded 200. Roughly 55% of everything the scrapers
collected was unreachable, which reads from the outside exactly like the
scrapers having stopped - the owner reported "still 330" while ingestion was
healthy and writing new rows every 30 minutes.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py"


class TestFeedLimit:
    def test_limit_is_configurable_not_hardcoded(self):
        source = ENDPOINT.read_text(encoding="utf-8")
        assert "settings.OPPORTUNITY_FEED_MAX_LIMIT" in source
        assert "min(limit, 200)" not in source, (
            "a hardcoded 200 cap hid most of the corpus once it grew past 200 rows"
        )

    def test_no_bare_200_slices_remain(self):
        """ids[:200] and limit=200 were separate copies of the same ceiling."""
        source = ENDPOINT.read_text(encoding="utf-8")
        assert "ids[:200]" not in source
        assert not re.search(r"_load_active_opportunities\(limit=200\)", source)

    def test_ceiling_exceeds_current_corpus(self):
        """A ceiling below the corpus size is indistinguishable from broken ingestion."""
        assert settings.OPPORTUNITY_FEED_MAX_LIMIT >= 600, (
            "the active corpus was 743 rows; a lower ceiling silently truncates the feed"
        )

    def test_fetch_window_can_reach_the_ceiling(self):
        """The pre-filter window must be wider than the post-filter limit.

        Active/portal filtering happens in Python after the window is read, so a
        window equal to the limit would starve the result set.
        """
        source = ENDPOINT.read_text(encoding="utf-8")
        match = re.search(r"fetch_window = min\(max\(\(safe_skip \+ safe_limit\) \* (\d+), \d+\), (\d+)\)", source)
        assert match, "fetch_window shape changed; re-check that it still exceeds the limit"
        multiplier, window_cap = int(match.group(1)), int(match.group(2))
        assert multiplier >= 2
        assert window_cap > settings.OPPORTUNITY_FEED_MAX_LIMIT
