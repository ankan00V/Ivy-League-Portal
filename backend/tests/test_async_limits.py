import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.async_limits import LoopLocalSemaphore


async def _contend(limiter, *, users: int = 3) -> int:
    """Force waiters, which is what binds an asyncio.Semaphore to a loop.

    Semaphore.acquire() fast-paths while capacity remains and never touches the
    loop, so the bug only appears once a caller actually has to wait.
    """
    running = 0
    peak = 0

    async def one() -> None:
        nonlocal running, peak
        async with limiter:
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(one() for _ in range(users)))
    return peak


class TestLoopLocalSemaphore(unittest.TestCase):
    def test_plain_semaphore_breaks_across_loops(self) -> None:
        """Documents the failure this class exists to fix.

        scraper_fetch_bridge.fetch_page_sync runs asyncio.run() per fetch, so
        module-level clients saw a new loop every call.
        """
        shared = asyncio.Semaphore(1)
        asyncio.run(_contend(shared))
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(_contend(shared))
        self.assertIn("bound to a different event loop", str(ctx.exception))

    def test_survives_repeated_event_loops(self) -> None:
        limiter = LoopLocalSemaphore(1)
        for _ in range(3):
            self.assertEqual(asyncio.run(_contend(limiter)), 1)

    def test_enforces_the_limit_within_a_loop(self) -> None:
        limiter = LoopLocalSemaphore(2)
        self.assertEqual(asyncio.run(_contend(limiter, users=6)), 2)

    def test_limit_is_read_lazily(self) -> None:
        """Clients pass a lambda over settings, so config changes are picked up."""
        limit = 1
        limiter = LoopLocalSemaphore(lambda: limit)
        self.assertEqual(asyncio.run(_contend(limiter, users=4)), 1)
        limit = 3
        self.assertEqual(asyncio.run(_contend(limiter, users=6)), 3)

    def test_invalid_limit_falls_back_to_one(self) -> None:
        limiter = LoopLocalSemaphore(lambda: None)
        self.assertEqual(asyncio.run(_contend(limiter, users=3)), 1)


if __name__ == "__main__":
    unittest.main()
