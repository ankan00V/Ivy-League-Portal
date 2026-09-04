"""Two things the feed must not do on every request.

Measured against the live corpus, a signed-in user's first page took just over
three seconds. Almost none of that was computation: a round trip to the Supabase
pooler costs ~350ms, so the endpoint was simply making too many of them.

Both causes were configuration rather than code.

OPPORTUNITY_READ_BACKEND was still "mongo" long after Mongo stopped being
contacted at all, so the hottest endpoint in the product took the legacy
fallback - which pulls a window of at least 400 rows through the ODM and
discards most of them to return 20, rather than filtering in SQL. Same 20 rows
either way: 1378ms against 788ms.

And the staleness check ran a query on every request to ask whether the corpus
needed re-scraping, an answer that moves on the scale of minutes.

Feed 20 went from 3057ms to 786ms. These tests hold the two settings, because
both regressions are invisible - the feed still returns correct results, just
slowly enough that a user notices and nobody else does.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings


class TestFeedReadsFromPostgres(unittest.TestCase):
    def test_default_backend_is_postgres(self) -> None:
        self.assertEqual(
            str(settings.OPPORTUNITY_READ_BACKEND).strip().lower(),
            "postgres",
            "the feed is back on the legacy ODM path; it over-fetches ~400 rows to return 20",
        )

    def test_the_mongo_path_is_still_reachable_as_a_fallback(self) -> None:
        # Kept deliberately: a backend switch must never take the feed down.
        # This asserts the fallback exists, not that it is used.
        import inspect

        from app.api.api_v1.endpoints import opportunities

        source = inspect.getsource(opportunities._load_active_opportunities)
        self.assertIn("postgres feed read failed", source)


class TestStalenessCheckIsThrottled(unittest.IsolatedAsyncioTestCase):
    """The check guards a scrape trigger, not correctness."""

    async def test_repeat_calls_do_not_hit_the_database(self) -> None:
        from app.api.api_v1.endpoints import opportunities

        calls = {"n": 0}

        class _Q:
            def sort(self, *_a):
                return self

            def limit(self, *_a):
                return self

            async def to_list(self):
                calls["n"] += 1
                return []

        opportunities._LAST_STALENESS_CHECK_AT = 0.0
        with (
            patch.object(settings, "SCRAPER_ON_DEMAND_REFRESH_ENABLED", True),
            patch.object(settings, "JOBS_ENABLED", False),
            patch.object(settings, "FEED_STALENESS_CHECK_INTERVAL_SECONDS", 60.0),
            patch.object(opportunities.Opportunity, "find_many", lambda *a, **k: _Q()),
            patch(
                "app.services.scraper.get_scraper_runtime_status",
                return_value={"is_running": False},
            ),
            patch("app.services.scraper.run_scheduled_scrapers"),
        ):
            for _ in range(5):
                await opportunities._ensure_live_feed_if_stale()

        self.assertEqual(
            calls["n"], 1, "the staleness check queried the database on every request"
        )

    async def test_the_interval_is_configurable_and_positive(self) -> None:
        value = float(settings.FEED_STALENESS_CHECK_INTERVAL_SECONDS)
        self.assertGreater(value, 0.0)

    async def test_disabled_refresh_short_circuits_before_any_query(self) -> None:
        from app.api.api_v1.endpoints import opportunities

        opportunities._LAST_STALENESS_CHECK_AT = 0.0
        with patch.object(settings, "SCRAPER_ON_DEMAND_REFRESH_ENABLED", False):
            await opportunities._ensure_live_feed_if_stale()


if __name__ == "__main__":
    unittest.main()
