from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import settings
from app.core import metrics

logger = logging.getLogger(__name__)


class CrawleeUnavailableError(RuntimeError):
    """Raised when Crawlee is disabled, misconfigured, or temporarily unavailable."""


@dataclass(frozen=True)
class CrawleeFetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    elapsed_seconds: float
    metadata: dict[str, Any]


class CrawleeClient:
    """Bounded async gateway around Crawlee single-page fetchers."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._semaphore = asyncio.Semaphore(max(1, int(settings.CRAWLEE_MAX_CONCURRENT)))
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(settings.CRAWLEE_ENABLED)

    @staticmethod
    def _validate_target_url(url: str) -> str:
        candidate = str(url or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise CrawleeUnavailableError("crawlee_target_url_invalid")
        if parsed.username or parsed.password:
            raise CrawleeUnavailableError("crawlee_target_credentials_forbidden")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise CrawleeUnavailableError("crawlee_private_target_forbidden")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return candidate
        if not address.is_global:
            raise CrawleeUnavailableError("crawlee_private_target_forbidden")
        return candidate

    def _ensure_circuit_closed(self) -> None:
        if self._circuit_open_until > self._monotonic():
            raise CrawleeUnavailableError("crawlee_circuit_open")

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(settings.CRAWLEE_CIRCUIT_FAILURE_THRESHOLD))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = self._monotonic() + max(
                1.0,
                float(settings.CRAWLEE_CIRCUIT_RECOVERY_SECONDS),
            )

    @staticmethod
    def _record_metrics(engine: str, status: str, elapsed_seconds: float) -> None:
        metrics.init_metrics()
        if metrics.CRAWLEE_REQUESTS_TOTAL is not None:
            metrics.CRAWLEE_REQUESTS_TOTAL.labels(engine=engine, status=status).inc()
        if metrics.CRAWLEE_REQUEST_LATENCY_SECONDS is not None:
            metrics.CRAWLEE_REQUEST_LATENCY_SECONDS.labels(engine=engine).observe(max(0.0, elapsed_seconds))

    async def scrape(self, url: str, *, render: bool = False, timeout_seconds: float | None = None) -> CrawleeFetchResult:
        self._ensure_circuit_closed()
        url = self._validate_target_url(url)
        timeout = max(3.0, float(timeout_seconds or settings.CRAWLEE_TIMEOUT_SECONDS))
        use_playwright = bool(render and settings.CRAWLEE_USE_PLAYWRIGHT)
        engine = "playwright" if use_playwright else "beautifulsoup"
        started = self._monotonic()
        try:
            async with self._semaphore:
                payload = await asyncio.wait_for(
                    self._run_crawler(url, use_playwright=use_playwright, timeout_seconds=timeout),
                    timeout=timeout + 5.0,
                )
            html = str(payload.get("html") or "")
            if not html.strip():
                raise CrawleeUnavailableError("crawlee_empty_response")
            max_chars = max(1, int(settings.CRAWLEE_MAX_CONTENT_CHARS))
            html = html[:max_chars]
            self._record_success()
            elapsed = max(0.0, self._monotonic() - started)
            self._record_metrics(engine, "success", elapsed)
            return CrawleeFetchResult(
                url=url,
                final_url=str(payload.get("final_url") or url),
                status_code=int(payload.get("status_code") or 200),
                html=html,
                elapsed_seconds=elapsed,
                metadata={"provider": "crawlee", "engine": engine},
            )
        except Exception as exc:
            self._record_failure()
            self._record_metrics(engine, "failure", self._monotonic() - started)
            if isinstance(exc, CrawleeUnavailableError):
                raise
            raise CrawleeUnavailableError(f"crawlee_scrape_failed:{type(exc).__name__}") from exc

    async def _run_crawler(self, url: str, *, use_playwright: bool, timeout_seconds: float) -> dict[str, Any]:
        holder: dict[str, Any] = {}
        retries = max(0, int(settings.CRAWLEE_MAX_RETRIES))

        if use_playwright:
            try:
                from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
            except ImportError as exc:  # pragma: no cover
                raise CrawleeUnavailableError("crawlee_playwright_extra_missing") from exc

            crawler = PlaywrightCrawler(
                max_requests_per_crawl=1,
                max_request_retries=retries,
                headless=True,
                navigation_timeout=timedelta(seconds=max(3.0, timeout_seconds)),
            )

            @crawler.router.default_handler
            async def playwright_handler(context: PlaywrightCrawlingContext) -> None:
                await context.page.wait_for_timeout(max(0, int(settings.CRAWLEE_WAIT_FOR_MS)))
                holder["html"] = await context.page.content()
                holder["final_url"] = context.page.url or context.request.url
                response = context.http_response
                holder["status_code"] = int(response.status_code) if response is not None else 200

            await crawler.run([url])
            if not holder:
                raise CrawleeUnavailableError("crawlee_playwright_no_result")
            return holder

        try:
            from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
        except ImportError as exc:  # pragma: no cover
            raise CrawleeUnavailableError("crawlee_beautifulsoup_extra_missing") from exc

        crawler = BeautifulSoupCrawler(
            max_requests_per_crawl=1,
            max_request_retries=retries,
        )

        @crawler.router.default_handler
        async def soup_handler(context: BeautifulSoupCrawlingContext) -> None:
            holder["html"] = str(context.soup)
            holder["final_url"] = str(context.request.loaded_url or context.request.url)
            response = context.http_response
            holder["status_code"] = int(response.status_code) if response is not None else 200

        await crawler.run([url])
        if not holder:
            raise CrawleeUnavailableError("crawlee_beautifulsoup_no_result")
        return holder


crawlee_client = CrawleeClient()
