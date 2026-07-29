from __future__ import annotations

import asyncio
import weakref
from typing import Any, Callable


class LoopLocalSemaphore:
    """A concurrency limiter that binds per running event loop.

    `asyncio.Semaphore` attaches to the first event loop that awaits it. Any
    semaphore built at import time - as the module-level fetch-client singletons
    are - is therefore usable from exactly one loop for the process lifetime.

    `scraper_fetch_bridge.fetch_page_sync` calls `asyncio.run()` for every
    fetch, which creates a fresh loop each time. So the first render-backed
    fetch after boot succeeded and every subsequent one failed with:

        <asyncio.locks.Semaphore object at 0x...> is bound to a different
        event loop

    That silently disabled every source needing a managed/rendered fetch.
    tensorhack.com accumulated 102 failed run logs and zero ingested rows while
    its pages were perfectly parseable.

    This keeps one real semaphore per loop, so the concurrency cap still holds
    within any given loop. Entries are weakly keyed, so a finished loop's
    semaphore is collected with it.
    """

    def __init__(self, limit: Callable[[], int] | int) -> None:
        self._limit = limit
        self._per_loop: weakref.WeakKeyDictionary[Any, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )

    def _resolve_limit(self) -> int:
        value = self._limit() if callable(self._limit) else self._limit
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def _for_running_loop(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        semaphore = self._per_loop.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self._resolve_limit())
            self._per_loop[loop] = semaphore
        return semaphore

    async def __aenter__(self) -> "LoopLocalSemaphore":
        await self._for_running_loop().acquire()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        # Same loop as __aenter__ (guaranteed by `async with`), so this resolves
        # to the same semaphore instance that was acquired.
        self._for_running_loop().release()
