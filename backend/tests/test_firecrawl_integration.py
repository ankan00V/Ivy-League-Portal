from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.firecrawl_client import (  # noqa: E402
    FirecrawlClient,
    FirecrawlFetchResult,
    FirecrawlUnavailableError,
)
from app.services.source_discovery import FetchedPage, SourceHttpClient  # noqa: E402
from scripts.validate_env import _validate_firecrawl  # noqa: E402


class FakeDocument:
    def __init__(self) -> None:
        self.html = "<html><body><a href='/jobs/1'>ML Intern</a></body></html>"
        self.raw_html = None
        self.markdown = "[ML Intern](/jobs/1)"
        self.metadata = {
            "source_url": "https://careers.example.com/jobs",
            "status_code": 200,
            "credits_used": 1,
        }


class FakeSearchPayload:
    web = [
        SimpleNamespace(
            url="https://careers.example.com/students",
            title="Example Students",
            description="Internships and graduate roles.",
        )
    ]


class FakeSdk:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.scrape_calls: list[tuple[str, dict]] = []
        self.search_calls: list[tuple[str, dict]] = []

    async def scrape(self, url: str, **kwargs):
        self.scrape_calls.append((url, kwargs))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return FakeDocument()

    async def search(self, query: str, **kwargs):
        self.search_calls.append((query, kwargs))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return FakeSearchPayload()


class FakeFirecrawlGateway:
    def __init__(self, result: FirecrawlFetchResult) -> None:
        self.configured = True
        self.result = result
        self.calls: list[str] = []

    async def scrape(self, url: str, *, timeout_seconds: float | None = None) -> FirecrawlFetchResult:
        self.calls.append(url)
        return self.result


class ControlledSourceHttpClient(SourceHttpClient):
    def __init__(self, direct_page: FetchedPage, firecrawl: FakeFirecrawlGateway) -> None:
        super().__init__(timeout_seconds=1, firecrawl=firecrawl)  # type: ignore[arg-type]
        self.direct_page = direct_page
        self.direct_calls = 0

    async def _fetch_direct(self, url: str, timeout_seconds: float) -> FetchedPage:
        self.direct_calls += 1
        return self.direct_page


class TestFirecrawlClient(unittest.TestCase):
    def test_configured_requires_key_when_policy_requires_it(self) -> None:
        client = FirecrawlClient(sdk_client=FakeSdk())
        with (
            patch.object(settings, "FIRECRAWL_ENABLED", True),
            patch.object(settings, "FIRECRAWL_API_URL", "https://api.firecrawl.dev"),
            patch.object(settings, "FIRECRAWL_REQUIRE_API_KEY", True),
        ):
            for key in (None, "", "<firecrawl-api-key>", "replace-with-firecrawl-key"):
                with patch.object(settings, "FIRECRAWL_API_KEY", key):
                    self.assertFalse(client.configured)

    def test_scrape_normalizes_sdk_document(self) -> None:
        async def run() -> None:
            sdk = FakeSdk()
            client = FirecrawlClient(sdk_client=sdk)
            result = await client.scrape("https://careers.example.com", timeout_seconds=2)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.final_url, "https://careers.example.com/jobs")
            self.assertIn("ML Intern", result.html)
            self.assertEqual(sdk.scrape_calls[0][1]["formats"], ["html", "markdown", "links"])

        asyncio.run(run())

    def test_scrape_bounds_provider_content(self) -> None:
        async def run() -> None:
            client = FirecrawlClient(sdk_client=FakeSdk())
            with patch.object(settings, "FIRECRAWL_MAX_CONTENT_CHARS", 20):
                result = await client.scrape("https://careers.example.com", timeout_seconds=2)
            self.assertEqual(len(result.html), 20)
            self.assertEqual(len(result.markdown), 20)

        asyncio.run(run())

    def test_scrape_rejects_private_network_targets(self) -> None:
        async def run() -> None:
            sdk = FakeSdk()
            client = FirecrawlClient(sdk_client=sdk)
            for target in (
                "http://127.0.0.1/admin",
                "http://169.254.169.254/latest/meta-data",
                "http://10.0.0.5/internal",
                "http://service.internal/jobs",
                "http://user:password@example.com/jobs",
            ):
                with self.assertRaises(FirecrawlUnavailableError):
                    await client.scrape(target)
            self.assertEqual(sdk.scrape_calls, [])

        asyncio.run(run())

    def test_search_normalizes_web_results(self) -> None:
        async def run() -> None:
            client = FirecrawlClient(sdk_client=FakeSdk())
            rows = await client.search("software internship India", limit=5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].url, "https://careers.example.com/students")
            self.assertEqual(rows[0].title, "Example Students")

        asyncio.run(run())

    def test_circuit_opens_after_repeated_failures(self) -> None:
        async def run() -> None:
            client = FirecrawlClient(sdk_client=FakeSdk(fail=True))
            with patch.object(settings, "FIRECRAWL_CIRCUIT_FAILURE_THRESHOLD", 2):
                for _ in range(2):
                    with self.assertRaises(FirecrawlUnavailableError):
                        await client.scrape("https://careers.example.com", timeout_seconds=1)
                with self.assertRaisesRegex(FirecrawlUnavailableError, "circuit_open"):
                    await client.scrape("https://careers.example.com", timeout_seconds=1)

        asyncio.run(run())


class TestSourceHttpClientFirecrawlRouting(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = FirecrawlFetchResult(
            url="https://careers.example.com",
            final_url="https://careers.example.com/jobs",
            status_code=200,
            html="<html><body>Rendered internship listings</body></html>",
            markdown="Rendered internship listings",
            elapsed_seconds=0.2,
            metadata={},
        )

    def test_preferred_render_mode_uses_firecrawl_first(self) -> None:
        async def run() -> None:
            gateway = FakeFirecrawlGateway(self.rendered)
            direct = FetchedPage(
                url=self.rendered.url,
                final_url=self.rendered.url,
                status_code=200,
                text="<html>direct</html>",
                elapsed_seconds=0.1,
            )
            client = ControlledSourceHttpClient(direct, gateway)
            with (
                patch.object(settings, "FIRECRAWL_MODE", "preferred"),
                patch.object(settings, "SOURCE_FETCH_RATE_LIMIT", 1000.0),
            ):
                result = await client.fetch(self.rendered.url, render=True)
            self.assertEqual(result.provider, "firecrawl")
            self.assertEqual(client.direct_calls, 0)

        asyncio.run(run())


    def test_fallback_mode_renders_short_html(self) -> None:
        async def run() -> None:
            gateway = FakeFirecrawlGateway(self.rendered)
            direct = FetchedPage(
                url=self.rendered.url,
                final_url=self.rendered.url,
                status_code=200,
                text="<html></html>",
                elapsed_seconds=0.1,
                content_type="text/html",
            )
            client = ControlledSourceHttpClient(direct, gateway)
            with (
                patch.object(settings, "FIRECRAWL_MODE", "fallback"),
                patch.object(settings, "FIRECRAWL_MIN_HTML_LENGTH", 100),
                patch.object(settings, "SOURCE_FETCH_RATE_LIMIT", 1000.0),
            ):
                result = await client.fetch(self.rendered.url, render=True)
            self.assertEqual(result.provider, "firecrawl")
            self.assertEqual(client.direct_calls, 1)
            self.assertEqual(len(gateway.calls), 1)

        asyncio.run(run())

    def test_non_render_json_path_never_uses_firecrawl(self) -> None:
        async def run() -> None:
            gateway = FakeFirecrawlGateway(self.rendered)
            direct = FetchedPage(
                url="https://api.example.com/jobs",
                final_url="https://api.example.com/jobs",
                status_code=200,
                text='{"jobs": []}',
                elapsed_seconds=0.1,
                content_type="application/json",
            )
            client = ControlledSourceHttpClient(direct, gateway)
            with (
                patch.object(settings, "FIRECRAWL_MODE", "preferred"),
                patch.object(settings, "SOURCE_FETCH_RATE_LIMIT", 1000.0),
            ):
                result = await client.fetch(direct.url)
            self.assertEqual(result.provider, "direct")
            self.assertEqual(gateway.calls, [])

        asyncio.run(run())


class TestFirecrawlEnvValidation(unittest.TestCase):
    def test_disabled_firecrawl_does_not_require_placeholder_key_in_production(self) -> None:
        with (
            patch.object(settings, "FIRECRAWL_ENABLED", False),
            patch.object(settings, "FIRECRAWL_API_KEY", "<firecrawl-api-key>"),
            patch.object(settings, "FIRECRAWL_MODE", "fallback"),
        ):
            results = _validate_firecrawl(production=True)

        fatal_failures = [item for item in results if not item.ok and item.severity == "fatal"]
        self.assertEqual(fatal_failures, [])
