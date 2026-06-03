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


if __name__ == "__main__":
    unittest.main()
