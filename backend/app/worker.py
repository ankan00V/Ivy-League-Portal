from __future__ import annotations

import asyncio
import logging
import signal

from app.bootstrap import init_database
from app.core.metrics import init_metrics
from app.core.redis import close_redis
from app.services.job_runner import job_runner, register_default_jobs

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    client = await init_database()
    try:
        init_metrics()
        register_default_jobs()
        job_runner.start()
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:  # pragma: no cover - Windows fallback
                pass

        logger.info("VidyaVerse worker started")
        await stop_event.wait()
    finally:
        await job_runner.stop()
        await close_redis()
        client.close()
        logger.info("VidyaVerse worker stopped")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
