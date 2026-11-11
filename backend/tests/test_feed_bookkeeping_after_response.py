"""The feed made a student wait for rows about their own request to be written.

After ranking, the personalised feed awaited impression logging and a telemetry
insert before returning. Neither changes the response. Counted against the live
database a warm request made six round trips at roughly 0.3s each - the database
is in another region - and half of them were this bookkeeping.

They now run after the response has been produced. Two properties have to hold
for that to be safe: the task must be kept alive until it finishes, because the
event loop holds only a weak reference, and a failure must be recorded, because
by then there is no caller left to raise to.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import opportunities as endpoint


class AfterResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_caller_is_not_made_to_wait(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow():
            started.set()
            await release.wait()

        endpoint._after_response(_slow(), label="slow bookkeeping")
        # Control returns here immediately; the work has not finished.
        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertTrue(endpoint._background_bookkeeping)
        release.set()
        await asyncio.sleep(0.01)

    async def test_the_task_is_held_until_it_finishes_then_released(self):
        """The loop keeps only weak references; an unreferenced task can be
        collected before it runs."""
        done = asyncio.Event()

        async def _work():
            await asyncio.sleep(0.01)
            done.set()

        before = len(endpoint._background_bookkeeping)
        endpoint._after_response(_work(), label="held")
        self.assertEqual(len(endpoint._background_bookkeeping), before + 1)
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.sleep(0)
        self.assertEqual(len(endpoint._background_bookkeeping), before)

    async def test_a_failure_is_logged_not_lost_and_not_raised(self):
        async def _boom():
            raise TimeoutError("insert timed out")

        with self.assertLogs(endpoint.logger, level="ERROR") as logs:
            endpoint._after_response(_boom(), label="feed telemetry")
            await asyncio.sleep(0.01)
        joined = "\n".join(logs.output)
        self.assertIn("feed telemetry", joined)
        self.assertIn("after the response was sent", joined)


class EndpointWiringTests(unittest.TestCase):
    def _body(self) -> str:
        source = (
            BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py"
        ).read_text()
        start = source.index("async def get_personalized_recommendations(")
        return source[start : source.index('@router.get("/shortlist/me"', start)]

    def test_impression_logging_is_not_awaited_inline(self):
        body = self._body()
        self.assertNotIn("await interaction_service.log_impressions(", body)
        self.assertIn('_after_response(impressions_logged, label="feed impression logging")', body)

    def test_success_telemetry_is_not_awaited_inline(self):
        body = self._body()
        self.assertIn('_after_response(telemetry, label="feed telemetry")', body)

    def test_failure_telemetry_still_runs_inline(self):
        """On the error path there is no response to speed up, and the record
        of the failure is the one thing worth waiting for."""
        body = self._body()
        self.assertIn("await ranking_request_telemetry_service.log(", body)
        self.assertIn("success=False", body)


if __name__ == "__main__":
    unittest.main()
