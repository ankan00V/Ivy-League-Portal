"""A query that times out must fail, not hang its caller forever.

Ask AI returned nothing after every restart, and the process sat at 0% CPU with
nothing logged. The chain, traced with asyncio task stacks:

  * the vector rebuild's first page is SELECT * including the 384-float
    embedding, 1.7 MB per 500 rows. The server produces it in ~1s; the link to
    ap-southeast-2 delivered it in 5s on a good minute and past the 30s
    command_timeout on a bad one;
  * command_timeout cancelled the query, and Supabase's transaction-mode pooler
    never acknowledges a cancel request;
  * asyncpg's release waits for that acknowledgement with `budget = timeout`,
    and with no acquire timeout the budget is None - so handing the connection
    back waited forever, inside `pool.acquire().__aexit__`.

A timeout on this pooler was not a failure mode, it was a permanent hang. With
an acquire timeout asyncpg terminates the stuck connection instead, and the pool
opens a fresh one.
"""

import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

APP = BACKEND_ROOT / "app"


class TestEveryAcquireIsBounded(unittest.TestCase):
    def test_no_pool_acquire_without_a_timeout(self) -> None:
        # The sweep that matters. One unbounded acquire anywhere is one place a
        # slow statement can still wedge the process.
        # Parsed, not grepped: the explanation of this bug lives in docstrings
        # that quote `pool.acquire()`, and a text search cannot tell those
        # from calls.
        import ast

        offenders = []
        for path in APP.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "acquire"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "pool"
                    and not any(kw.arg == "timeout" for kw in node.keywords)
                ):
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], "unbounded pool.acquire() found")

    def test_the_budget_outlasts_the_command_timeout(self) -> None:
        # Shorter than the command timeout would cut off a query that
        # legitimately ran close to it, on its way back to the pool.
        from app.core.config import settings
        from app.db.pg_documents import acquire_timeout

        self.assertGreater(acquire_timeout(), float(settings.NEON_COMMAND_TIMEOUT_SECONDS))

    def test_asyncpg_still_uses_the_acquire_timeout_as_the_release_budget(self) -> None:
        # The fix rests on this detail of asyncpg. If an upgrade stops passing
        # the acquire timeout through to release, the hang comes back silently.
        import inspect

        from asyncpg import pool

        source = inspect.getsource(pool.Pool._acquire)
        self.assertIn("ch._timeout = timeout", source)
        self.assertIn("timeout = ch._timeout", inspect.getsource(pool.Pool.release))


class TestVectorPagesStayShort(unittest.TestCase):
    def test_a_page_is_small_enough_to_beat_the_timeout_on_a_slow_link(self) -> None:
        from app.core.config import settings

        self.assertLessEqual(int(settings.VECTOR_LOAD_PAGE_SIZE), 100)


class _SlowIndex:
    """Enough of the vector service to exercise _ensure_index."""

    def __init__(self, build_seconds: float) -> None:
        from app.services.vector_service import OpportunityVectorService

        self._service = OpportunityVectorService.__new__(OpportunityVectorService)
        self._service._last_build_at = None
        self.builds = 0
        self._seconds = build_seconds

        async def rebuild(force: bool = False) -> None:
            self.builds += 1
            await asyncio.sleep(self._seconds)
            self._service._last_build_at = 1.0

        self._service.rebuild = rebuild

    @property
    def service(self):
        return self._service


class TestTheFirstBuildOutlivesItsRequest(unittest.IsolatedAsyncioTestCase):
    """The build that makes Ask AI ready must not die with the request.

    Retrieval is capped at 45s and the full build takes ~84s over this link, so
    awaiting it inline meant the cap cancelled it every time and the next
    request started from nothing. With warmup disabled, the index could never
    become ready.
    """

    async def test_a_timed_out_request_does_not_cancel_the_build(self) -> None:
        index = _SlowIndex(build_seconds=0.3)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(index.service._ensure_index(), timeout=0.05)
        # The request gave up; the build carries on and finishes.
        await asyncio.sleep(0.4)
        self.assertTrue(index.service.is_ready())

    async def test_concurrent_first_requests_share_one_build(self) -> None:
        index = _SlowIndex(build_seconds=0.1)
        await asyncio.gather(*(index.service._ensure_index() for _ in range(5)))
        self.assertEqual(index.builds, 1)
        self.assertTrue(index.service.is_ready())

    async def test_a_ready_index_is_not_rebuilt(self) -> None:
        index = _SlowIndex(build_seconds=0.1)
        await index.service._ensure_index()
        await index.service._ensure_index()
        self.assertEqual(index.builds, 1)


if __name__ == "__main__":
    unittest.main()


class TestTheExistingVectorReadIsChunked(unittest.TestCase):
    """The second whole-corpus read, found once build failures were logged.

    After the load succeeded, `_sync_persistent_vectors` fetched every existing
    vector entry in one statement - ~10 MB of embeddings - which crossed the
    command timeout. The build failed after doing all the expensive work, the
    index never became ready, and every Ask AI request started another build.
    """

    def test_the_in_query_is_issued_per_chunk(self) -> None:
        import inspect

        from app.services.vector_service import OpportunityVectorService

        source = inspect.getsource(OpportunityVectorService._sync_persistent_vectors)
        self.assertIn("opp_ids[start : start + chunk]", source)
        self.assertNotIn("In(VectorIndexEntry.opportunity_id, opp_ids))", source)

    def test_a_failed_build_is_logged_not_swallowed(self) -> None:
        import inspect

        from app.services.vector_service import OpportunityVectorService

        source = inspect.getsource(OpportunityVectorService._background_refresh)
        self.assertIn("logger.exception", source)
