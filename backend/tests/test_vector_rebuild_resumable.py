"""A cancelled vector rebuild must keep the rows it already wrote.

embeddings.rebuild runs under JOBS_HANDLER_TIMEOUT_SECONDS. It used to
accumulate every changed row and write them in one _flush at the very end, so
when the deadline fired mid-write the entire batch was discarded and the next
run recomputed exactly the same rows - and lost them again. The job died that
way 93 consecutive times while last_error said only "job_timeout:900.0s";
nothing anywhere said the work was being thrown away.

The property under test is not speed, it is that progress accumulates: whatever
a run finishes before it is killed stays finished.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import vector_service as vs


class TestFlushInBatches(unittest.IsolatedAsyncioTestCase):
    async def test_rows_are_written_in_chunks_not_one_call(self) -> None:
        calls = []

        async def fake_flush(model_cls, instances):
            calls.append(len(instances))
            return len(instances)

        with (
            patch.object(vs, "_flush", fake_flush),
            patch.object(vs.settings, "VECTOR_FLUSH_BATCH_SIZE", 200),
        ):
            written = await vs._flush_in_batches(object, list(range(450)), label="x")

        self.assertEqual(written, 450)
        self.assertEqual(calls, [200, 200, 50])

    async def test_work_completed_before_cancellation_is_kept(self) -> None:
        # The regression itself. Kill the flush partway and assert the earlier
        # chunks already landed rather than being rolled back with the run.
        landed = []

        async def fake_flush(model_cls, instances):
            if len(landed) >= 2:
                raise asyncio.CancelledError()
            landed.extend(instances)
            return len(instances)

        with (
            patch.object(vs, "_flush", fake_flush),
            patch.object(vs.settings, "VECTOR_FLUSH_BATCH_SIZE", 1),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await vs._flush_in_batches(object, ["a", "b", "c", "d"], label="x")

        self.assertEqual(landed, ["a", "b"], "committed chunks must survive the cancellation")

    async def test_empty_input_does_no_round_trips(self) -> None:
        calls = []

        async def fake_flush(model_cls, instances):
            calls.append(len(instances))
            return len(instances)

        with patch.object(vs, "_flush", fake_flush):
            self.assertEqual(await vs._flush_in_batches(object, [], label="x"), 0)
        self.assertEqual(calls, [])

    async def test_batch_size_is_never_zero(self) -> None:
        # A misconfigured 0 would make range() step by zero and hang the job.
        calls = []

        async def fake_flush(model_cls, instances):
            calls.append(len(instances))
            return len(instances)

        with (
            patch.object(vs, "_flush", fake_flush),
            patch.object(vs.settings, "VECTOR_FLUSH_BATCH_SIZE", 0),
        ):
            written = await vs._flush_in_batches(object, ["a", "b"], label="x")
        self.assertEqual(written, 2)
        self.assertEqual(calls, [1, 1])


if __name__ == "__main__":
    unittest.main()
