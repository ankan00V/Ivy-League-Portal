import asyncio
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import rate_limit as rate_limit_module
from app.core.rate_limit import check_rate_limit


class _ExplodingRedis:
    async def incr(self, *_args, **_kwargs):
        raise ConnectionError("redis unreachable")


class TestRateLimitFailureMode(unittest.IsolatedAsyncioTestCase):
    """Losing Redis must not silently disable brute-force protection.

    The limiter previously returned None - which the middleware reads as
    "allowed" - on both an unconfigured client and any exception, with no log
    and no metric. A Redis blip therefore removed every limit in the
    application, including the auth limiter, and was indistinguishable from
    healthy operation.
    """

    def setUp(self) -> None:
        # These paths log at error level by design; keep test output readable.
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    async def test_auth_paths_fail_closed_when_redis_is_absent(self) -> None:
        with patch.object(rate_limit_module, "get_redis", return_value=None):
            decision = await check_rate_limit(
                subject="1.2.3.4", action="/auth/login", limit_per_minute=30, fail_closed=True
            )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.retry_after_seconds, 0)

    async def test_auth_paths_fail_closed_when_redis_errors(self) -> None:
        with patch.object(rate_limit_module, "get_redis", return_value=_ExplodingRedis()):
            decision = await check_rate_limit(
                subject="1.2.3.4", action="/auth/login", limit_per_minute=30, fail_closed=True
            )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertFalse(decision.allowed)

    async def test_non_auth_paths_still_degrade_open(self) -> None:
        """Browsing should survive a Redis outage; sign-in should not."""
        with patch.object(rate_limit_module, "get_redis", return_value=None):
            decision = await check_rate_limit(
                subject="1.2.3.4", action="/opportunities", limit_per_minute=240
            )
        self.assertIsNone(decision)

    async def test_failure_is_logged(self) -> None:
        logging.disable(logging.NOTSET)
        with patch.object(rate_limit_module, "get_redis", return_value=None):
            with self.assertLogs("app.core.rate_limit", level="ERROR") as captured:
                await check_rate_limit(
                    subject="1.2.3.4", action="/auth/login", limit_per_minute=30, fail_closed=True
                )
        self.assertTrue(any("rate limit backend unavailable" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
