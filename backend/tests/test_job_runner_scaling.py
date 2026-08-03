import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services import job_runner as job_runner_module
from app.services.job_runner import JobRunner


def _job(job_type: str = "test.slow", payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"{job_type}-1",
        job_type=job_type,
        payload=payload or {},
        attempts=0,
        max_attempts=1,
    )


class TestJobRunnerScaling(unittest.IsolatedAsyncioTestCase):
    async def test_run_job_marks_timeout_as_failure(self) -> None:
        runner = JobRunner()

        async def slow_handler(_: dict) -> dict:
            await asyncio.sleep(0.2)
            return {"status": "late"}

        runner.register("test.slow", slow_handler)
        mark_failure = AsyncMock()

        with patch.object(settings, "JOBS_HANDLER_TIMEOUT_SECONDS", 0.01), patch.object(
            runner, "_mark_failure", new=mark_failure
        ):
            await runner._run_job(_job())

        mark_failure.assert_awaited_once()
        self.assertTrue(mark_failure.await_args.kwargs["error"].startswith("job_timeout:"))

    async def test_loop_dispatches_up_to_configured_concurrency(self) -> None:
        runner = JobRunner()
        pending_jobs = [_job(payload={"idx": 1}), _job(payload={"idx": 2})]
        started: list[int] = []
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def claim_next():
            if pending_jobs:
                return pending_jobs.pop(0)
            await asyncio.sleep(0.01)
            return None

        async def slow_handler(payload: dict) -> dict:
            started.append(int(payload["idx"]))
            if len(started) == 2:
                both_started.set()
            await release.wait()
            return {"status": "ok"}

        runner.register("test.slow", slow_handler)
        runner._claim_next = claim_next  # type: ignore[method-assign]

        with patch.object(settings, "JOBS_MAX_CONCURRENCY", 2), patch.object(
            settings, "JOBS_POLL_INTERVAL_SECONDS", 0.01
        ), patch.object(settings, "JOBS_HANDLER_TIMEOUT_SECONDS", 1.0), patch.object(
            runner, "_mark_success", new=AsyncMock()
        ):
            loop_task = asyncio.create_task(runner._loop())
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
            runner._stop_event.set()
            release.set()
            await asyncio.wait_for(loop_task, timeout=1.0)

        self.assertEqual(sorted(started), [1, 2])

    async def test_enqueue_rejects_when_per_type_queue_is_full(self) -> None:
        runner = JobRunner()

        class FakeCollection:
            async def count_documents(self, query: dict) -> int:
                self.query = query
                return 2

        with patch.object(settings, "JOBS_MAX_PENDING_PER_TYPE", 2), patch.object(
            job_runner_module, "_get_collection", return_value=FakeCollection()
        ):
            with self.assertRaisesRegex(RuntimeError, "job_queue_full:test.queue"):
                await runner.enqueue(job_type="test.queue")


class TestAbandonedJobReclamation(unittest.IsolatedAsyncioTestCase):
    """A worker that dies mid-job must not leak its queue slot forever.

    `running` rows were previously unclaimable while still counting toward
    JOBS_MAX_PENDING_PER_TYPE and blocking their dedupe_key, so repeated
    restarts wedged the queue permanently.
    """

    class _CapturingCollection:
        def __init__(self) -> None:
            self.query: dict = {}

        async def find_one_and_update(self, query, update, **kwargs):
            self.query = query
            return None

    async def _claim_query(self) -> dict:
        runner = JobRunner()
        collection = self._CapturingCollection()
        with patch.object(job_runner_module, "_get_collection", return_value=collection):
            await runner._claim_next()
        return collection.query

    async def test_claim_query_includes_abandoned_running_jobs(self) -> None:
        query = await self._claim_query()

        branches = query.get("$or") or []
        running_branches = [b for b in branches if b.get("status") == "running"]
        self.assertTrue(
            running_branches,
            "claim query must be able to reclaim abandoned 'running' jobs",
        )
        self.assertIn("locked_at", running_branches[0])

    async def test_reclaim_cutoff_clears_the_handler_timeout(self) -> None:
        """Reclaiming at the lock timeout alone would double-run a healthy job.

        JOBS_LOCK_TIMEOUT_SECONDS (600) is shorter than
        JOBS_HANDLER_TIMEOUT_SECONDS (900), so a live job can outlive its lock.
        """
        with patch.object(settings, "JOBS_LOCK_TIMEOUT_SECONDS", 600), patch.object(
            settings, "JOBS_HANDLER_TIMEOUT_SECONDS", 900.0
        ):
            query = await self._claim_query()

        branches = query.get("$or") or []
        running = next(b for b in branches if b.get("status") == "running")
        pending = next(b for b in branches if b.get("status") != "running")

        reclaim_cutoff = running["locked_at"]["$lte"]
        lock_cutoff = pending["$or"][1]["locked_at"]["$lte"]

        # The abandoned cutoff must be strictly older than the lock cutoff.
        self.assertLess(reclaim_cutoff, lock_cutoff)


if __name__ == "__main__":
    unittest.main()
