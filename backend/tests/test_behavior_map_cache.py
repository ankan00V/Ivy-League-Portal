"""Behaviour priors were rebuilt from the database on every feed request.

`_build_behavior_map` reads 120 days of a user's interactions and aggregates
them in Python. Profiled against the live database it cost 1.0-1.3s per call,
and a warm ranking call measured 2.0s of which essentially all was I/O wait -
the scoring itself is under half a second. One round trip to a database in
another region, repeated per request, was the feed.

A minute of staleness is immaterial: these are aggregates over four months, so
one more click cannot meaningfully move them.
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

from app.services import recommendation_service as mod
from app.services.recommendation_service import RecommendationService

EMPTY = {"domain": {}, "type": {}, "source": {}, "domain_ctr": {}, "source_ctr": {}, "stats": {}}


class BehaviorCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = RecommendationService()

    async def test_the_second_request_does_not_hit_the_database(self):
        calls = []

        async def _compute(uid):
            calls.append(uid)
            return dict(EMPTY)

        with patch.object(self.service, "_compute_behavior_map", side_effect=_compute):
            a = await self.service._build_behavior_map("u1")
            b = await self.service._build_behavior_map("u1")
        self.assertEqual(len(calls), 1)
        self.assertIs(a, b)

    async def test_each_user_is_cached_separately(self):
        """A shared entry would hand one student another's behaviour priors."""
        calls = []

        async def _compute(uid):
            calls.append(uid)
            return {"stats": {"who": uid}}

        with patch.object(self.service, "_compute_behavior_map", side_effect=_compute):
            one = await self.service._build_behavior_map("u1")
            two = await self.service._build_behavior_map("u2")
        self.assertEqual(calls, ["u1", "u2"])
        self.assertEqual(one["stats"]["who"], "u1")
        self.assertEqual(two["stats"]["who"], "u2")

    async def test_a_burst_for_one_user_queries_once(self):
        calls = []

        async def _compute(uid):
            calls.append(uid)
            await asyncio.sleep(0.05)
            return dict(EMPTY)

        with patch.object(self.service, "_compute_behavior_map", side_effect=_compute):
            await asyncio.gather(*(self.service._build_behavior_map("u1") for _ in range(8)))
        self.assertEqual(len(calls), 1)

    async def test_an_expired_entry_is_rebuilt(self):
        calls = []

        async def _compute(uid):
            calls.append(uid)
            return dict(EMPTY)

        with patch.object(self.service, "_compute_behavior_map", side_effect=_compute):
            await self.service._build_behavior_map("u1")
            stamp, value = self.service._behavior_cache["u1"]
            self.service._behavior_cache["u1"] = (stamp - mod._BEHAVIOR_CACHE_TTL_SECONDS - 1, value)
            await self.service._build_behavior_map("u1")
        self.assertEqual(len(calls), 2)

    async def test_the_cache_is_bounded(self):
        """A long-running process must not accumulate an entry per user ever
        seen."""
        async def _compute(uid):
            return dict(EMPTY)

        with (
            patch.object(self.service, "_compute_behavior_map", side_effect=_compute),
            patch.object(mod, "_BEHAVIOR_CACHE_MAX_USERS", 5),
        ):
            for i in range(12):
                await self.service._build_behavior_map(f"u{i}")
        self.assertLessEqual(len(self.service._behavior_cache), 6)
        self.assertLessEqual(len(self.service._behavior_locks), 6)

    def test_the_window_is_short_against_the_data_it_summarises(self):
        """120 days of history behind a 60-second cache: one click cannot move
        the aggregate enough to matter."""
        self.assertLessEqual(mod._BEHAVIOR_CACHE_TTL_SECONDS, 300)
        self.assertGreater(mod._BEHAVIOR_CACHE_TTL_SECONDS, 0)


if __name__ == "__main__":
    unittest.main()
