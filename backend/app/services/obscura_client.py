"""Bounded async gateway around the Obscura headless browser.

Obscura fills a real gap between the two fetchers already here. Scrapling
defeats bot detection but is an HTTP client and does not execute JavaScript, so
a careers page that mounts its job board client-side comes back as an empty
shell - measured on Airtable and Accor, both of which returned a full page with
zero job links. Crawlee can run JavaScript, but drives Playwright, whose sync
API is not thread-safe: launching it across concurrent workers produced repeated
"Connection closed while reading from the driver" failures that fell back
silently, so rendering appeared to run while returning the unrendered HTML.

Obscura is a single Rust binary embedding V8. It renders, it is far lighter than
a full Chrome, and being a subprocess per fetch it has no shared-state
concurrency problem. Measured against pages that had defeated both existing
fetchers it recovered about a third, including boards on SuccessFactors that
nothing else had surfaced.

It sits between the other two rather than replacing either: scrapling stays
first because it is much faster when JavaScript is not needed, and crawlee stays
last because Obscura does not succeed everywhere - some targets return nothing.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.async_limits import LoopLocalSemaphore
from app.core.config import settings

logger = logging.getLogger(__name__)


class ObscuraUnavailableError(RuntimeError):
    """Raised when Obscura is disabled, missing, or temporarily unavailable."""


@dataclass(frozen=True)
class ObscuraFetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    elapsed_seconds: float
    metadata: dict[str, Any]


class ObscuraClient:
    """Runs the Obscura binary one URL at a time, under a concurrency cap."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._semaphore = LoopLocalSemaphore(lambda: settings.OBSCURA_MAX_CONCURRENT)
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._resolved_binary: str | None = None

    def binary_path(self) -> str | None:
        """Explicit setting first, then PATH. Cached once resolved."""
        if self._resolved_binary and os.path.isfile(self._resolved_binary):
            return self._resolved_binary
        configured = str(getattr(settings, "OBSCURA_BINARY_PATH", "") or "").strip()
        if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
            self._resolved_binary = configured
            return configured
        found = shutil.which("obscura")
        self._resolved_binary = found
        return found

    @property
    def configured(self) -> bool:
        # A missing binary is a normal state, not a misconfiguration: the render
        # chain simply skips to the next provider.
        return bool(settings.OBSCURA_ENABLED) and bool(self.binary_path())

    @staticmethod
    def _validate_target_url(url: str) -> str:
        candidate = str(url or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ObscuraUnavailableError("obscura_target_url_invalid")
        if parsed.username or parsed.password:
            raise ObscuraUnavailableError("obscura_target_credentials_forbidden")
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ObscuraUnavailableError("obscura_private_target_forbidden")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return candidate
        if not address.is_global:
            raise ObscuraUnavailableError("obscura_private_target_forbidden")
        return candidate

    def _ensure_circuit_closed(self) -> None:
        if self._circuit_open_until > self._monotonic():
            raise ObscuraUnavailableError("obscura_circuit_open")

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(settings.OBSCURA_CIRCUIT_FAILURE_THRESHOLD))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = self._monotonic() + max(
                1.0, float(settings.OBSCURA_CIRCUIT_RECOVERY_SECONDS)
            )

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> ObscuraFetchResult:
        self._ensure_circuit_closed()
        binary = self.binary_path()
        if not binary:
            raise ObscuraUnavailableError("obscura_binary_missing")
        url = self._validate_target_url(url)
        timeout = max(5.0, float(timeout_seconds or settings.OBSCURA_TIMEOUT_SECONDS))

        # argv list, never a shell string: the URL is passed as a single
        # argument, so no amount of shell metacharacters in it can become
        # executable. _validate_target_url has already rejected non-http
        # schemes, embedded credentials and private-network targets.
        argv = [binary, "fetch", url]
        if settings.OBSCURA_STEALTH:
            argv.append("--stealth")
        if settings.OBSCURA_OBEY_ROBOTS:
            argv.append("--obey-robots")

        started = self._monotonic()
        try:
            async with self._semaphore:
                # subprocess.run on a worker thread, not asyncio's subprocess
                # machinery. On macOS a fork() issued by a process that has
                # already used Apple's Network framework - which any TLS request
                # does - crashes the child inside its atfork handlers before it
                # can exec. It shows up as a SIGSEGV in nw_settings_child_has_forked
                # and takes the whole interpreter down, which under concurrency
                # produced a stream of "Python quit unexpectedly" crashes and
                # meant this provider returned nothing at all. subprocess.run
                # goes through posix_spawn instead, so no fork happens.
                completed = await asyncio.to_thread(
                    subprocess.run,
                    argv,
                    capture_output=True,
                    timeout=timeout,
                )

            if completed.returncode != 0:
                detail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                raise ObscuraUnavailableError(
                    f"obscura_exit_{completed.returncode}:"
                    f"{detail[-1][:120] if detail else 'no_output'}"
                )

            html = (completed.stdout or b"").decode("utf-8", "replace")
            if not html.strip():
                raise ObscuraUnavailableError("obscura_empty_response")
            html = html[: max(1, int(settings.OBSCURA_MAX_CONTENT_CHARS))]

            self._record_success()
            elapsed = max(0.0, self._monotonic() - started)
            return ObscuraFetchResult(
                url=url,
                final_url=url,
                status_code=200,
                html=html,
                elapsed_seconds=elapsed,
                metadata={
                    "provider": "obscura",
                    "engine": "v8",
                    "stealth": bool(settings.OBSCURA_STEALTH),
                },
            )
        except subprocess.TimeoutExpired as exc:
            # run() has already killed the child, so no browser is left behind.
            self._record_failure()
            raise ObscuraUnavailableError("obscura_timeout") from exc
        except Exception as exc:
            self._record_failure()
            if isinstance(exc, ObscuraUnavailableError):
                raise
            raise ObscuraUnavailableError(f"obscura_scrape_failed:{type(exc).__name__}") from exc


obscura_client = ObscuraClient()
