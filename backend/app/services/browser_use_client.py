from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlparse

from app.core.config import settings
from app.core import metrics

logger = logging.getLogger(__name__)


def _is_placeholder(value: str | None) -> bool:
    candidate = str(value or "").strip().lower()
    return not candidate or candidate.startswith("<") or candidate.startswith("replace-")


class BrowserUseUnavailableError(RuntimeError):
    """Raised when Browser Use is disabled, misconfigured, or temporarily unavailable."""


@dataclass(frozen=True)
class BrowserUseFetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    elapsed_seconds: float
    metadata: dict[str, Any]


class BrowserUseClient:
    """Bounded async gateway around Browser Use Cloud CDP sessions."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._semaphore = asyncio.Semaphore(max(1, int(settings.BROWSER_USE_MAX_CONCURRENT)))
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def configured(self) -> bool:
        if not settings.BROWSER_USE_ENABLED:
            return False
        return not _is_placeholder(settings.BROWSER_USE_API_KEY)

    @staticmethod
    def _validate_target_url(url: str) -> str:
        candidate = str(url or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise BrowserUseUnavailableError("browser_use_target_url_invalid")
        if parsed.username or parsed.password:
            raise BrowserUseUnavailableError("browser_use_target_credentials_forbidden")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise BrowserUseUnavailableError("browser_use_private_target_forbidden")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return candidate
        if not address.is_global:
            raise BrowserUseUnavailableError("browser_use_private_target_forbidden")
        return candidate

    def _wss_url(self) -> str:
        api_key = str(settings.BROWSER_USE_API_KEY or "").strip()
        if _is_placeholder(api_key):
            raise BrowserUseUnavailableError("browser_use_api_key_missing")
        country = str(settings.BROWSER_USE_PROXY_COUNTRY or "us").strip().lower() or "us"
        return (
            f"wss://connect.browser-use.com?apiKey={quote(api_key, safe='')}"
            f"&proxyCountryCode={quote(country, safe='')}"
        )

    def _ensure_circuit_closed(self) -> None:
        if self._circuit_open_until > self._monotonic():
            raise BrowserUseUnavailableError("browser_use_circuit_open")

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(settings.BROWSER_USE_CIRCUIT_FAILURE_THRESHOLD))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = self._monotonic() + max(
                1.0,
                float(settings.BROWSER_USE_CIRCUIT_RECOVERY_SECONDS),
            )

    @staticmethod
    def _record_metrics(status: str, elapsed_seconds: float) -> None:
        metrics.init_metrics()
        if metrics.BROWSER_USE_REQUESTS_TOTAL is not None:
            metrics.BROWSER_USE_REQUESTS_TOTAL.labels(status=status).inc()
        if metrics.BROWSER_USE_REQUEST_LATENCY_SECONDS is not None:
            metrics.BROWSER_USE_REQUEST_LATENCY_SECONDS.observe(max(0.0, elapsed_seconds))

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> BrowserUseFetchResult:
        self._ensure_circuit_closed()
        url = self._validate_target_url(url)
        timeout = max(5.0, float(timeout_seconds or settings.BROWSER_USE_TIMEOUT_SECONDS))
        started = self._monotonic()
        try:
            async with self._semaphore:
                html, final_url, status_code = await asyncio.wait_for(
                    self._fetch_via_cdp(url, timeout),
                    timeout=timeout + 5.0,
                )
            if not html.strip():
                raise BrowserUseUnavailableError("browser_use_empty_response")
            max_chars = max(1, int(settings.BROWSER_USE_MAX_CONTENT_CHARS))
            html = html[:max_chars]
            self._record_success()
            elapsed = max(0.0, self._monotonic() - started)
            self._record_metrics("success", elapsed)
            return BrowserUseFetchResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                html=html,
                elapsed_seconds=elapsed,
                metadata={"provider": "browser_use"},
            )
        except Exception as exc:
            self._record_failure()
            self._record_metrics("failure", self._monotonic() - started)
            if isinstance(exc, BrowserUseUnavailableError):
                raise
            raise BrowserUseUnavailableError(f"browser_use_scrape_failed:{type(exc).__name__}") from exc

    async def _fetch_via_cdp(self, url: str, timeout_seconds: float) -> tuple[str, str, int]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise BrowserUseUnavailableError("browser_use_playwright_missing") from exc

        timeout_ms = int(timeout_seconds * 1000)
        wss_url = self._wss_url()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(wss_url)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                await page.wait_for_timeout(max(0, int(settings.BROWSER_USE_WAIT_FOR_MS)))
                html = await page.content()
                final_url = page.url or url
                status_code = int(response.status) if response is not None else 200
                return html, final_url, status_code
            finally:
                await browser.close()


browser_use_client = BrowserUseClient()
