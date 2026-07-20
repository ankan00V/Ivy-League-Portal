from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.browser_use_client import (  # noqa: E402
    BrowserUseClient,
    BrowserUseFetchResult,
    BrowserUseUnavailableError,
)
from app.services.crawlee_client import (  # noqa: E402
    CrawleeClient,
    CrawleeFetchResult,
    CrawleeUnavailableError,
)
from app.services.firecrawl_client import FirecrawlFetchResult  # noqa: E402
from app.services.firecrawl_client import FirecrawlUnavailableError  # noqa: E402
from app.services.source_discovery import FetchedPage, SourceHttpClient  # noqa: E402


class FakeBrowserUseGateway:
    def __init__(self, result: BrowserUseFetchResult) -> None:
        self.configured = True
        self.result = result
        self.calls: list[str] = []

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> BrowserUseFetchResult:
        self.calls.append(url)
        return self.result


class FakeCrawleeGateway:
    def __init__(self, result: CrawleeFetchResult) -> None:
        self.configured = True
        self.result = result
        self.calls: list[str] = []

    async def scrape(self, url: str, *, render: bool = False, timeout_seconds: float | None = None) -> CrawleeFetchResult:
        self.calls.append(url)
        return self.result


class FakeFirecrawlGateway:
    def __init__(self, *, fail: bool = False) -> None:
        self.configured = True
        self.fail = fail
        self.calls: list[str] = []

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> FirecrawlFetchResult:
        self.calls.append(url)
        if self.fail:
            raise FirecrawlUnavailableError("firecrawl_down")
        return FirecrawlFetchResult(
            url=url,
            final_url=f"{url}/jobs",
            status_code=200,
            html="<html><body>firecrawl</body></html>",
            markdown="firecrawl",
            elapsed_seconds=0.1,
            metadata={},
        )


class ControlledMultiProviderClient(SourceHttpClient):
    def __init__(
        self,
        direct_page: FetchedPage,
        *,
        firecrawl: FakeFirecrawlGateway | None = None,
        browser_use: FakeBrowserUseGateway | None = None,
        crawlee: FakeCrawleeGateway | None = None,
    ) -> None:
        super().__init__(
            timeout_seconds=1,
            firecrawl=firecrawl,  # type: ignore[arg-type]
            browser_use=browser_use,  # type: ignore[arg-type]
            crawlee=crawlee,  # type: ignore[arg-type]
        )
        self.direct_page = direct_page
        self.direct_calls = 0

    async def _fetch_direct(self, url: str, timeout_seconds: float) -> FetchedPage:
        self.direct_calls += 1
        return self.direct_page


class TestBrowserUseClient(unittest.TestCase):
    def test_configured_requires_key(self) -> None:
        client = BrowserUseClient()
        with patch.object(settings, "BROWSER_USE_ENABLED", True):
            for key in (None, "", "<browser-use-api-key>"):
                with patch.object(settings, "BROWSER_USE_API_KEY", key):
                    self.assertFalse(client.configured)

    def test_scrape_via_cdp(self) -> None:
        async def run() -> None:
            client = BrowserUseClient()

            async def fake_fetch(url: str, timeout: float) -> tuple[str, str, int]:
                self.assertEqual(url, "https://careers.example.com")
                return "<html>browser-use</html>", "https://careers.example.com/jobs", 200

            with patch.object(client, "_fetch_via_cdp", fake_fetch):
                result = await client.scrape("https://careers.example.com", timeout_seconds=5)
            self.assertEqual(result.provider if hasattr(result, "provider") else result.metadata.get("provider"), "browser_use")
            self.assertIn("browser-use", result.html)

        asyncio.run(run())


class TestCrawleeClient(unittest.TestCase):
    def test_scrape_uses_beautifulsoup_engine(self) -> None:
        async def run() -> None:
            client = CrawleeClient()

            async def fake_run(url: str, *, use_playwright: bool, timeout_seconds: float) -> dict[str, str | int]:
                self.assertFalse(use_playwright)
                return {
                    "html": "<html><body>crawlee</body></html>",
                    "final_url": url,
                    "status_code": 200,
                }

            with (
                patch.object(settings, "CRAWLEE_ENABLED", True),
                patch.object(client, "_run_crawler", fake_run),
            ):
                result = await client.scrape("https://careers.example.com", render=False, timeout_seconds=5)
            self.assertEqual(result.metadata["engine"], "beautifulsoup")
            self.assertIn("crawlee", result.html)

        asyncio.run(run())

    def test_scrape_rejects_private_targets(self) -> None:
        async def run() -> None:
            client = CrawleeClient()
            with patch.object(settings, "CRAWLEE_ENABLED", True):
                with self.assertRaises(CrawleeUnavailableError):
                    await client.scrape("http://127.0.0.1/admin")

        asyncio.run(run())


class TestMultiProviderRouting(unittest.TestCase):
    def test_fallback_chain_uses_browser_use_after_firecrawl(self) -> None:
        async def run() -> None:
            direct = FetchedPage(
                url="https://careers.example.com",
                final_url="https://careers.example.com",
                status_code=200,
                text="<html></html>",
                elapsed_seconds=0.1,
                content_type="text/html",
            )
            browser_use = FakeBrowserUseGateway(
                BrowserUseFetchResult(
                    url=direct.url,
                    final_url=f"{direct.url}/jobs",
                    status_code=200,
                    html="<html><body>Rendered listings</body></html>",
                    elapsed_seconds=0.2,
                    metadata={},
                )
            )
            client = ControlledMultiProviderClient(
                direct,
                firecrawl=FakeFirecrawlGateway(fail=True),
                browser_use=browser_use,
            )
            with (
                patch.object(settings, "FIRECRAWL_MODE", "fallback"),
                patch.object(settings, "BROWSER_USE_MODE", "fallback"),
                patch.object(settings, "CRAWLEE_MODE", "disabled"),
                patch.object(settings, "FIRECRAWL_MIN_HTML_LENGTH", 100),
                patch.object(settings, "SOURCE_FETCH_RATE_LIMIT", 1000.0),
            ):
                result = await client.fetch(direct.url, render=True)
            self.assertEqual(result.provider, "browser_use")
            self.assertEqual(client.direct_calls, 1)
            self.assertEqual(len(browser_use.calls), 1)
            self.assertTrue(browser_use.calls[0].startswith("https://careers.example.com"))

        asyncio.run(run())

    def test_fallback_chain_uses_crawlee_last(self) -> None:
        async def run() -> None:
            direct = FetchedPage(
                url="https://careers.example.com",
                final_url="https://careers.example.com",
                status_code=403,
                text="blocked",
                elapsed_seconds=0.1,
                content_type="text/html",
            )
            crawlee = FakeCrawleeGateway(
                CrawleeFetchResult(
                    url=direct.url,
                    final_url=f"{direct.url}/jobs",
                    status_code=200,
                    html="<html><body>Crawlee rendered</body></html>",
                    elapsed_seconds=0.3,
                    metadata={"engine": "playwright"},
                )
            )
            client = ControlledMultiProviderClient(
                direct,
                firecrawl=FakeFirecrawlGateway(fail=True),
                browser_use=FakeBrowserUseGateway(
                    BrowserUseFetchResult(
                        url=direct.url,
                        final_url=direct.url,
                        status_code=500,
                        html="",
                        elapsed_seconds=0.1,
                        metadata={},
                    )
                ),
                crawlee=crawlee,
            )

            async def failing_browser_use(url: str, timeout_seconds: float) -> FetchedPage:
                raise BrowserUseUnavailableError("browser_use_down")

            client._fetch_browser_use = failing_browser_use  # type: ignore[method-assign]

            with (
                patch.object(settings, "FIRECRAWL_MODE", "fallback"),
                patch.object(settings, "BROWSER_USE_MODE", "fallback"),
                patch.object(settings, "CRAWLEE_MODE", "fallback"),
                patch.object(settings, "SOURCE_FETCH_RATE_LIMIT", 1000.0),
            ):
                result = await client.fetch(direct.url, render=True)
            self.assertEqual(result.provider, "crawlee")
            self.assertEqual(len(crawlee.calls), 1)
            self.assertTrue(crawlee.calls[0].startswith("https://careers.example.com"))

        asyncio.run(run())
