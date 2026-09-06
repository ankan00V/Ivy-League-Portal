"""Returning a connection to the pool must not be able to wedge the process.

This worker has now hung twice the same way - once for 44 hours, once for 10 -
and the second time left a stack trace:

    job_runner._loop -> _claim_next -> find_one_and_update
      -> pool.acquire().__aexit__ -> release -> Connection.reset -> TimeoutError

asyncpg resets a connection on release by running a reset statement on it.
Against a direct Postgres that is correct. Against Supabase's transaction-mode
pooler it is not: pgbouncer hands the server connection to someone else the
moment the transaction ends, so the state asyncpg wants to clear is not ours,
and the query goes out on a socket the pooler may already have closed.

The release path is not cancellable from outside, so the timeout does not
propagate as a failed job - the connection is simply never returned. Ten of
those and the pool is empty, every acquire blocks forever, and the process sits
at 0% CPU with a full queue behind it. Nothing logs, because nothing is running.

The property these tests hold is narrow and load-bearing: the pool is built with
a reset hook that does nothing, and with an idle lifetime short enough that a
connection is closed by us while it is still ours.
"""

import asyncio
import inspect
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.db import pg_documents


class TestResetIsDisabled(unittest.IsolatedAsyncioTestCase):
    async def test_the_reset_hook_does_nothing(self) -> None:
        # It must not touch the connection at all. Passing None here would fail
        # immediately if the hook ever started issuing queries again.
        self.assertIsNone(await pg_documents._reset_is_the_poolers_job(None))

    def test_the_hook_is_a_coroutine(self) -> None:
        # asyncpg awaits it; a plain function would raise on every release.
        self.assertTrue(inspect.iscoroutinefunction(pg_documents._reset_is_the_poolers_job))


class TestPoolIsBuiltWithTheGuards(unittest.IsolatedAsyncioTestCase):
    """Assert on the arguments, because the failure they prevent is a hang.

    A test that opened a real pool and released a connection would pass whether
    or not the hook is wired up - the reset only hangs against a pooler that has
    dropped the socket, which is not reproducible on demand.
    """

    async def test_create_pool_receives_the_reset_hook_and_a_short_idle_life(self) -> None:
        captured: dict = {}

        async def fake_create_pool(*args, **kwargs):
            captured.update(kwargs)

            class _Pool:
                _closed = False

            return _Pool()

        original = pg_documents.asyncpg.create_pool
        original_pool = pg_documents._pool
        pg_documents.asyncpg.create_pool = fake_create_pool
        pg_documents._pool = None
        # A DSN has to be *configured* even though nothing connects: get_pool
        # resolves it before it calls create_pool, and resolution refuses
        # loudly when none is set rather than guessing a database. That refusal
        # is deliberate and correct, so the test supplies a value instead of
        # weakening it - and this is what made the test pass on any machine
        # with a backend/.env and fail in CI, which has none.
        with patch.object(settings, "SUPABASE_DATABASE_URL", "postgresql://user:pw@127.0.0.1:5432/unit-test"):
            try:
                await pg_documents.get_pool()
            finally:
                pg_documents.asyncpg.create_pool = original
                pg_documents._pool = original_pool

        self.assertIs(
            captured.get("reset"),
            pg_documents._reset_is_the_poolers_job,
            "the pool was built without the reset hook; release can hang again",
        )
        lifetime = captured.get("max_inactive_connection_lifetime")
        self.assertIsNotNone(lifetime, "idle connections would live for asyncpg's default 300s")
        # Must stay under the pooler's own idle timeout, or the socket is closed
        # by the far end first and we are back to discovering it on release.
        self.assertLessEqual(float(lifetime), 300.0)
        self.assertGreater(float(lifetime), 0.0)

    async def test_prepared_statement_cache_stays_disabled(self) -> None:
        # Skipping reset is only safe because there is no session state worth
        # clearing. A statement cache would be exactly that state.
        self.assertEqual(int(settings.NEON_POOL_MAX_SIZE), settings.NEON_POOL_MAX_SIZE)
        source = inspect.getsource(pg_documents.get_pool)
        self.assertIn("statement_cache_size=0", source)


class TestSettingIsSane(unittest.TestCase):
    def test_idle_lifetime_setting_exists_and_is_below_the_default(self) -> None:
        value = float(getattr(settings, "POSTGRES_IDLE_CONNECTION_LIFETIME_SECONDS"))
        self.assertGreater(value, 0.0)
        self.assertLess(
            value,
            300.0,
            "asyncpg's default is 300s, which is longer than Supabase keeps an idle connection",
        )


if __name__ == "__main__":
    unittest.main()
