from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.async_limits import LoopLocalSemaphore
from app.core.config import settings
from app.core.url_guard import BlockedTargetURL, assert_public_http_url

logger = logging.getLogger(__name__)


class ScraplingUnavailableError(RuntimeError):
    """Raised when Scrapling cannot serve this request."""


@dataclass(frozen=True)
class ScraplingResult:
    html: str
    final_url: str
    status_code: int
    elapsed_seconds: float


class ScraplingClient:
    """Local, free anti-bot fetcher.

    Sits ahead of the paid providers in the chain. Scrapling's stealth headers
    and TLS impersonation clear sources that a plain requests/httpx GET cannot:
    measured against the two sources that were hard-blocked, news.columbia.edu
    went 403 -> 200 (141k chars) and wellfound.com/jobs went 403 -> 200 with 72
    job links. Both are BSD-3 licensed and run in-process, so recovering them
    costs nothing per call, unlike Firecrawl.

    Only the HTTP fetcher is used here. The browser-backed StealthyFetcher is
    deliberately not wired in: Crawlee and Browser Use already cover rendering,
    and a third headless browser is a large dependency for little gain.
    """

    def __init__(self) -> None:
        self._semaphore = LoopLocalSemaphore(lambda: settings.SCRAPLING_MAX_CONCURRENT)
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(settings.SCRAPLING_ENABLED)

    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(settings.SCRAPLING_CIRCUIT_FAILURE_THRESHOLD))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = time.monotonic() + float(
                settings.SCRAPLING_CIRCUIT_RECOVERY_SECONDS
            )
            logger.warning(
                "scrapling circuit opened after %d consecutive failures",
                self._consecutive_failures,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _fetch_sync(self, url: str, timeout_seconds: float) -> ScraplingResult:
        from scrapling.fetchers import Fetcher

        started = time.monotonic()
        page = Fetcher.get(url, stealthy_headers=True, timeout=int(timeout_seconds))
        body = getattr(page, "body", "") or ""
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", errors="replace")
        return ScraplingResult(
            html=str(body),
            final_url=str(getattr(page, "url", url) or url),
            status_code=int(getattr(page, "status", 0) or 0),
            elapsed_seconds=max(0.0, time.monotonic() - started),
        )

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> ScraplingResult:
        if not self.configured:
            raise ScraplingUnavailableError("scrapling_disabled")
        if self._circuit_is_open():
            raise ScraplingUnavailableError("scrapling_circuit_open")
        # Re-validated here rather than trusting the caller: this client is one
        # branch of a provider chain and must not become an SSRF bypass.
        try:
            target = assert_public_http_url(url)
        except BlockedTargetURL as exc:
            raise ScraplingUnavailableError(f"scrapling_target_forbidden:{exc}") from exc

        timeout = float(timeout_seconds or settings.SCRAPLING_TIMEOUT_SECONDS)
        async with self._semaphore:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_sync, target, timeout),
                    timeout=timeout + 10.0,
                )
            except Exception as exc:
                self._record_failure()
                raise ScraplingUnavailableError(f"scrapling_fetch_failed:{type(exc).__name__}") from exc

        if result.status_code >= 400 or not result.html.strip():
            self._record_failure()
            raise ScraplingUnavailableError(f"scrapling_bad_response:{result.status_code}")

        self._record_success()
        return result


scrapling_client = ScraplingClient()
