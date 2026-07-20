from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from app.core.config import settings
from app.services.source_discovery import FetchedPage, SourceHttpClient

logger = logging.getLogger(__name__)

_shared_client: SourceHttpClient | None = None
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="scraper-fetch")


def get_scraper_http_client() -> SourceHttpClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = SourceHttpClient(timeout_seconds=float(settings.SCRAPER_TIMEOUT_SECONDS))
    return _shared_client


async def fetch_page(url: str, *, render: bool = False, timeout_seconds: float | None = None) -> FetchedPage:
    client = get_scraper_http_client()
    return await client.fetch(url, render=render, timeout_seconds=timeout_seconds)


def fetch_page_sync(url: str, *, render: bool = False, timeout_seconds: float | None = None) -> FetchedPage:
    """Run the async fetch pipeline from synchronous scraper code."""

    async def _run() -> FetchedPage:
        return await fetch_page(url, render=render, timeout_seconds=timeout_seconds)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    future = _executor.submit(asyncio.run, _run())
    return future.result()


def fetch_response_like(
    url: str,
    *,
    render: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Return a requests-like payload for legacy scraper call sites."""

    page = fetch_page_sync(url, render=render, timeout_seconds=timeout_seconds)
    return {
        "url": page.final_url,
        "text": page.text,
        "status_code": page.status_code,
        "headers": {"content-type": page.content_type},
        "provider": page.provider,
    }
