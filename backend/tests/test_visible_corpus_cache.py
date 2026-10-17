"""The feed read the whole opportunities table on every request.

`Opportunity.find_many().to_list()` with no filter and no limit, once per
personalised feed request, then filtered and ranked in Python. Measured against
the live database that read alone was 8 seconds warm and 13 cold, inside a page
that took 20 seconds end to end.

The read is identical for every user - same rows, same visibility rule, same
ordering - and only the ranking afterwards is personal. So it happens once and
is shared for a short window.

The window is deliberately short. The scraper writes continuously and a student
refreshing after applying should see the feed move, so 30 seconds sits far
below the scrape interval while still collapsing a burst into one read.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import opportunities as endpoint


class CorpusCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        endpoint._visible_corpus_cache["rows"] = None
        endpoint._visible_corpus_cache["at"] = 0.0

    def tearDown(self):
        endpoint._visible_corpus_cache["rows"] = None
        endpoint._visible_corpus_cache["at"] = 0.0

    def _patch_db(self, rows=None, counter=None):
        async def _to_list():
            if counter is not None:
                counter.append(1)
            return rows or []

        find_many = patch.object(
            endpoint.Opportunity, "find_many", return_value=type("Q", (), {"to_list": staticmethod(_to_list)})()
        )
        passthrough = patch.object(endpoint, "_filter_active_opportunities", side_effect=lambda r: list(r))
        return find_many, passthrough

    async def test_the_second_request_does_not_touch_the_database(self):
        reads: list[int] = []
        fm, pf = self._patch_db(rows=["a", "b"], counter=reads)
        with fm, pf:
            first = await endpoint._load_visible_opportunities()
            second = await endpoint._load_visible_opportunities()
        self.assertEqual(len(reads), 1)
        self.assertEqual(first, second)

    async def test_a_burst_of_concurrent_requests_reads_once(self):
        """Without the re-check inside the lock, every request that arrived on
        a cold cache ran its own full table scan - the exact behaviour this
        change exists to remove."""
        reads: list[int] = []

        async def _slow_to_list():
            reads.append(1)
            await asyncio.sleep(0.05)
            return ["a"]

        with (
            patch.object(
                endpoint.Opportunity, "find_many",
                return_value=type("Q", (), {"to_list": staticmethod(_slow_to_list)})(),
            ),
            patch.object(endpoint, "_filter_active_opportunities", side_effect=lambda r: list(r)),
        ):
            await asyncio.gather(*(endpoint._load_visible_opportunities() for _ in range(8)))
        self.assertEqual(len(reads), 1)

    async def test_an_expired_window_reloads(self):
        reads: list[int] = []
        fm, pf = self._patch_db(rows=["a"], counter=reads)
        with fm, pf:
            await endpoint._load_visible_opportunities()
            # Age the entry past the window rather than sleeping through it.
            endpoint._visible_corpus_cache["at"] -= endpoint._VISIBLE_CORPUS_TTL_SECONDS + 1
            await endpoint._load_visible_opportunities()
        self.assertEqual(len(reads), 2)

    async def test_force_bypasses_a_warm_cache(self):
        reads: list[int] = []
        fm, pf = self._patch_db(rows=["a"], counter=reads)
        with fm, pf:
            await endpoint._load_visible_opportunities()
            await endpoint._load_visible_opportunities(force=True)
        self.assertEqual(len(reads), 2)

    async def test_the_visibility_rule_still_runs(self):
        """Caching must not become a way to serve rows the feed should hide."""
        seen = {}

        def _filter(rows):
            seen["called"] = True
            return [r for r in rows if r != "hidden"]

        with (
            patch.object(
                endpoint.Opportunity, "find_many",
                return_value=type("Q", (), {"to_list": staticmethod(AsyncMock(return_value=["a", "hidden"]))})(),
            ),
            patch.object(endpoint, "_filter_active_opportunities", side_effect=_filter),
        ):
            rows = await endpoint._load_visible_opportunities()
        self.assertTrue(seen.get("called"))
        self.assertEqual(rows, ["a"])

    def test_the_window_stays_below_the_scrape_interval(self):
        """A cache longer than the write cadence would hide new listings for a
        meaningful part of their life."""
        from app.core.config import settings

        self.assertLess(
            endpoint._VISIBLE_CORPUS_TTL_SECONDS,
            settings.SCRAPER_INTERVAL_MINUTES * 60,
        )


class CallSiteTests(unittest.TestCase):
    def test_no_feed_path_reads_the_whole_table_directly(self):
        source = (
            BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py"
        ).read_text()
        # The call-site form, not the mention of it in the cache's own comment.
        self.assertNotIn(
            "opportunities = _filter_active_opportunities(await Opportunity.find_many().to_list())",
            source,
        )
        self.assertIn("opportunities = await _load_visible_opportunities()", source)


if __name__ == "__main__":
    unittest.main()
