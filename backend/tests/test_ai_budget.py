"""The endpoints that spend money are metered against the account spending it.

Ask AI and the assistant each run retrieval, a cross-encoder and an LLM
generation, so every call has a bill attached. The HTTP middleware does not
cover that case: it is keyed by IP at a default of 240 requests per minute,
which is roughly 14,000 model calls an hour from a single address.

IP is also the wrong key here in both directions. A college behind one NAT
shares a single bucket, so real students throttle each other, while anyone with
rotating addresses is not limited at all.

Fails closed on purpose. If Redis is unreachable the spend cannot be counted,
and an uncounted paid endpoint is worse than a brief refusal - the same
reasoning the credential endpoints already use.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import RateLimitDecision, enforce_ai_budget


def _allowed(limit=12):
    return RateLimitDecision(allowed=True, remaining=limit - 1, limit=limit, retry_after_seconds=0)


def _blocked(limit=12, retry=37):
    return RateLimitDecision(allowed=False, remaining=0, limit=limit, retry_after_seconds=retry)


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_request_inside_both_windows_passes(self):
        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(return_value=_allowed())),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_allowed(300))),
        ):
            await enforce_ai_budget(user_id="u1", action="ai.ask")

    async def test_the_per_minute_window_refuses_with_retry_after(self):
        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(return_value=_blocked())),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_allowed(300))),
        ):
            with self.assertRaises(HTTPException) as caught:
                await enforce_ai_budget(user_id="u1", action="ai.ask")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "37")
        self.assertIn("per minute", caught.exception.detail)

    async def test_the_daily_ceiling_catches_a_slow_drip(self):
        """A trickle under the per-minute limit still adds up to a month's
        budget in a day, which the minute window alone cannot see."""
        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(return_value=_allowed())),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_blocked(300, 1200))),
        ):
            with self.assertRaises(HTTPException) as caught:
                await enforce_ai_budget(user_id="u1", action="ai.ask")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn("per day", caught.exception.detail)

    async def test_each_account_has_its_own_bucket(self):
        """The whole point of moving off the IP key."""
        seen: list[str] = []

        async def _record(*, subject, action, limit_per_minute, fail_closed):
            seen.append(subject)
            return _allowed()

        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(side_effect=_record)),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_allowed(300))),
        ):
            await enforce_ai_budget(user_id="student-a", action="ai.ask")
            await enforce_ai_budget(user_id="student-b", action="ai.ask")
        self.assertEqual(seen, ["student-a", "student-b"])

    async def test_surfaces_are_counted_separately(self):
        actions: list[str] = []

        async def _record(*, subject, action, limit_per_minute, fail_closed):
            actions.append(action)
            return _allowed()

        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(side_effect=_record)),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_allowed(300))),
        ):
            await enforce_ai_budget(user_id="u1", action="ai.ask")
            await enforce_ai_budget(user_id="u1", action="ai.chat")
        self.assertEqual(actions, ["ai.ask", "ai.chat"])

    async def test_it_asks_the_limiter_to_fail_closed(self):
        captured = {}

        async def _record(*, subject, action, limit_per_minute, fail_closed):
            captured["fail_closed"] = fail_closed
            captured["limit"] = limit_per_minute
            return _allowed()

        with (
            patch.object(rate_limit, "check_rate_limit", new=AsyncMock(side_effect=_record)),
            patch.object(rate_limit, "_check_daily", new=AsyncMock(return_value=_allowed(300))),
        ):
            await enforce_ai_budget(user_id="u1", action="ai.ask")
        self.assertTrue(captured["fail_closed"])
        self.assertEqual(captured["limit"], settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE)


class ConfigTests(unittest.TestCase):
    def test_the_ai_budget_is_far_below_the_generic_http_limit(self):
        """If these ever converge the budget has stopped meaning anything."""
        self.assertLess(
            settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE,
            settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
        )
        self.assertGreater(settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE, 0)
        self.assertGreater(settings.RATE_LIMIT_AI_REQUESTS_PER_DAY, settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE)


class WiringTests(unittest.TestCase):
    """The helper is only worth anything if the paid routes actually call it."""

    def test_ask_ai_is_metered(self):
        source = (BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py").read_text()
        self.assertIn('enforce_ai_budget(user_id=str(current_user.id), action="ai.ask")', source)

    def test_the_assistant_is_metered(self):
        source = (BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "chat.py").read_text()
        self.assertIn('enforce_ai_budget(user_id=str(current_user.id), action="ai.chat")', source)


if __name__ == "__main__":
    unittest.main()
