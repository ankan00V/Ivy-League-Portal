from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import warnings
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import settings
from app.core import metrics

logger = logging.getLogger(__name__)


def _is_placeholder(value: str | None) -> bool:
    candidate = str(value or "").strip().lower()
    return not candidate or candidate.startswith("<") or candidate.startswith("replace-")


class FirecrawlUnavailableError(RuntimeError):
    """Raised when Firecrawl is disabled, misconfigured, or temporarily unavailable."""


@dataclass(frozen=True)
class FirecrawlFetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    markdown: str
    elapsed_seconds: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FirecrawlSearchResult:
    url: str
    title: str | None = None
    description: str | None = None


class FirecrawlClient:
    """Bounded async gateway around the Firecrawl SDK.

    The gateway owns concurrency and circuit-breaker behavior so callers can
    fall back without coupling the ingestion pipeline to Firecrawl internals.
    """

    def __init__(
        self,
        *,
        sdk_client: Any | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sdk_client = sdk_client
        self._monotonic = monotonic
        self._semaphore = asyncio.Semaphore(max(1, int(settings.FIRECRAWL_MAX_CONCURRENT)))
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    @property
    def configured(self) -> bool:
        if not settings.FIRECRAWL_ENABLED or not str(settings.FIRECRAWL_API_URL or "").strip():
            return False
        return bool(
            not settings.FIRECRAWL_REQUIRE_API_KEY
            or not _is_placeholder(settings.FIRECRAWL_API_KEY)
        )

    @staticmethod
    def _validate_target_url(url: str) -> str:
        candidate = str(url or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise FirecrawlUnavailableError("firecrawl_target_url_invalid")
        if parsed.username or parsed.password:
            raise FirecrawlUnavailableError("firecrawl_target_credentials_forbidden")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise FirecrawlUnavailableError("firecrawl_private_target_forbidden")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return candidate
        if not address.is_global:
            raise FirecrawlUnavailableError("firecrawl_private_target_forbidden")
        return candidate

    def _client(self) -> Any:
        if self._sdk_client is not None:
            return self._sdk_client
        if not self.configured:
            raise FirecrawlUnavailableError("firecrawl_disabled")
        api_key = str(settings.FIRECRAWL_API_KEY or "").strip()
        if settings.FIRECRAWL_REQUIRE_API_KEY and _is_placeholder(api_key):
            raise FirecrawlUnavailableError("firecrawl_api_key_missing")
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r'Field name "json".*shadows an attribute')
                from firecrawl import AsyncFirecrawl
        except ImportError as exc:  # pragma: no cover - deployment packaging failure
            raise FirecrawlUnavailableError("firecrawl_sdk_missing") from exc
        self._sdk_client = AsyncFirecrawl(
            api_key=api_key or None,
            api_url=str(settings.FIRECRAWL_API_URL).rstrip("/"),
            timeout=float(settings.FIRECRAWL_TIMEOUT_SECONDS),
            max_retries=max(0, int(settings.FIRECRAWL_MAX_RETRIES)),
            backoff_factor=max(0.0, float(settings.FIRECRAWL_RETRY_BACKOFF_SECONDS)),
        )
        return self._sdk_client

    def _ensure_circuit_closed(self) -> None:
        if self._circuit_open_until > self._monotonic():
            raise FirecrawlUnavailableError("firecrawl_circuit_open")

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(settings.FIRECRAWL_CIRCUIT_FAILURE_THRESHOLD))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = self._monotonic() + max(
                1.0,
                float(settings.FIRECRAWL_CIRCUIT_RECOVERY_SECONDS),
            )

    @staticmethod
    def _record_metrics(operation: str, status: str, elapsed_seconds: float) -> None:
        metrics.init_metrics()
        if metrics.FIRECRAWL_REQUESTS_TOTAL is not None:
            metrics.FIRECRAWL_REQUESTS_TOTAL.labels(operation=operation, status=status).inc()
        if metrics.FIRECRAWL_REQUEST_LATENCY_SECONDS is not None:
            metrics.FIRECRAWL_REQUEST_LATENCY_SECONDS.labels(operation=operation).observe(
                max(0.0, elapsed_seconds)
            )

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> FirecrawlFetchResult:
        self._ensure_circuit_closed()
        url = self._validate_target_url(url)
        client = self._client()
        timeout = max(1.0, float(timeout_seconds or settings.FIRECRAWL_TIMEOUT_SECONDS))
        started = self._monotonic()
        try:
            async with self._semaphore:
                document = await asyncio.wait_for(
                    client.scrape(
                        url,
                        formats=["html", "markdown", "links"],
                        only_main_content=False,
                        timeout=int(timeout * 1000),
                        wait_for=max(0, int(settings.FIRECRAWL_WAIT_FOR_MS)),
                        remove_base64_images=True,
                        block_ads=True,
                        max_age=max(0, int(settings.FIRECRAWL_CACHE_MAX_AGE_MS)),
                    ),
                    timeout=timeout + 2.0,
                )
            metadata_model = getattr(document, "metadata", None)
            metadata = (
                metadata_model.model_dump(exclude_none=True)
                if hasattr(metadata_model, "model_dump")
                else dict(metadata_model or {})
            )
            html = str(getattr(document, "html", None) or getattr(document, "raw_html", None) or "")
            markdown = str(getattr(document, "markdown", None) or "")
            if not html and not markdown:
                raise FirecrawlUnavailableError("firecrawl_empty_response")
            max_chars = max(1, int(settings.FIRECRAWL_MAX_CONTENT_CHARS))
            html = html[:max_chars]
            markdown = markdown[:max_chars]
            final_url = str(metadata.get("source_url") or metadata.get("url") or url)
            status_code = int(metadata.get("status_code") or 200)
            self._record_success()
            elapsed = max(0.0, self._monotonic() - started)
            self._record_metrics("scrape", "success", elapsed)
            return FirecrawlFetchResult(
                url=url,
                final_url=final_url,
                status_code=status_code,
                html=html,
                markdown=markdown,
                elapsed_seconds=elapsed,
                metadata=metadata,
            )
        except Exception as exc:
            self._record_failure()
            self._record_metrics("scrape", "failure", self._monotonic() - started)
            if isinstance(exc, FirecrawlUnavailableError):
                raise
            raise FirecrawlUnavailableError(f"firecrawl_scrape_failed:{type(exc).__name__}") from exc

    async def search(self, query: str, *, limit: int = 5) -> list[FirecrawlSearchResult]:
        self._ensure_circuit_closed()
        client = self._client()
        started = self._monotonic()
        try:
            async with self._semaphore:
                payload = await asyncio.wait_for(
                    client.search(
                        query,
                        limit=max(1, min(10, int(limit))),
                        sources=[{"type": "web"}],
                        scrape_options={"formats": ["markdown"], "only_main_content": True},
                    ),
                    timeout=max(3.0, float(settings.FIRECRAWL_TIMEOUT_SECONDS) + 2.0),
                )
            rows = getattr(payload, "web", None) or []
            results: list[FirecrawlSearchResult] = []
            for row in rows:
                url = str(getattr(row, "url", None) or "").strip()
                if not url:
                    continue
                try:
                    url = self._validate_target_url(url)
                except FirecrawlUnavailableError:
                    continue
                metadata = getattr(row, "metadata", None)
                results.append(
                    FirecrawlSearchResult(
                        url=url,
                        title=(
                            str(getattr(row, "title", None) or getattr(metadata, "title", None) or "").strip()
                            or None
                        ),
                        description=(
                            str(
                                getattr(row, "description", None)
                                or getattr(metadata, "description", None)
                                or ""
                            ).strip()
                            or None
                        ),
                    )
                )
            self._record_success()
            self._record_metrics("search", "success", self._monotonic() - started)
            return results
        except Exception as exc:
            self._record_failure()
            self._record_metrics("search", "failure", self._monotonic() - started)
            if isinstance(exc, FirecrawlUnavailableError):
                raise
            logger.warning("Firecrawl search failed", extra={"error_type": type(exc).__name__})
            raise FirecrawlUnavailableError(f"firecrawl_search_failed:{type(exc).__name__}") from exc


firecrawl_client = FirecrawlClient()
