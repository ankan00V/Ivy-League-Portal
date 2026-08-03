import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import url_guard
from app.services import scrapling_client as module
from app.services.scrapling_client import ScraplingClient, ScraplingResult, ScraplingUnavailableError


def _ok(html: str = "<html><body>listing</body></html>") -> ScraplingResult:
    return ScraplingResult(html=html, final_url="https://example.com/jobs", status_code=200, elapsed_seconds=0.1)


class TestScraplingClient(unittest.IsolatedAsyncioTestCase):
    """Local, free anti-bot fetcher placed ahead of the paid providers.

    Measured against the two sources that were hard-blocked:
    news.columbia.edu 403 -> 200 and wellfound.com/jobs 403 -> 200.
    """

    def setUp(self) -> None:
        self.client = ScraplingClient()

    async def test_returns_page_on_success(self) -> None:
        with (
            patch.object(module.settings, "SCRAPLING_ENABLED", True),
            patch.object(url_guard, "resolve_hostname", return_value=["93.184.216.34"]),
            patch.object(ScraplingClient, "_fetch_sync", return_value=_ok()),
        ):
            result = await self.client.scrape("https://example.com/jobs")
        self.assertEqual(result.status_code, 200)
        self.assertIn("listing", result.html)

    async def test_disabled_client_refuses(self) -> None:
        with patch.object(module.settings, "SCRAPLING_ENABLED", False):
            with self.assertRaises(ScraplingUnavailableError):
                await self.client.scrape("https://example.com/jobs")

    async def test_ssrf_guard_is_reapplied(self) -> None:
        """One branch of a provider chain must not become an SSRF bypass."""
        with patch.object(module.settings, "SCRAPLING_ENABLED", True):
            with self.assertRaises(ScraplingUnavailableError) as ctx:
                await self.client.scrape("http://169.254.169.254/latest/meta-data/")
        self.assertIn("forbidden", str(ctx.exception))

    async def test_error_response_is_treated_as_failure(self) -> None:
        blocked = ScraplingResult(html="", final_url="x", status_code=403, elapsed_seconds=0.1)
        with (
            patch.object(module.settings, "SCRAPLING_ENABLED", True),
            patch.object(url_guard, "resolve_hostname", return_value=["93.184.216.34"]),
            patch.object(ScraplingClient, "_fetch_sync", return_value=blocked),
        ):
            with self.assertRaises(ScraplingUnavailableError):
                await self.client.scrape("https://example.com/jobs")

    async def test_circuit_opens_after_repeated_failures(self) -> None:
        """A site that consistently blocks must not be retried every cycle."""
        boom = ScraplingResult(html="", final_url="x", status_code=500, elapsed_seconds=0.1)
        with (
            patch.object(module.settings, "SCRAPLING_ENABLED", True),
            patch.object(module.settings, "SCRAPLING_CIRCUIT_FAILURE_THRESHOLD", 2),
            patch.object(url_guard, "resolve_hostname", return_value=["93.184.216.34"]),
            patch.object(ScraplingClient, "_fetch_sync", return_value=boom),
        ):
            for _ in range(2):
                with self.assertRaises(ScraplingUnavailableError):
                    await self.client.scrape("https://example.com/jobs")
            with self.assertRaises(ScraplingUnavailableError) as ctx:
                await self.client.scrape("https://example.com/jobs")
        self.assertIn("circuit_open", str(ctx.exception))

    async def test_success_resets_the_failure_count(self) -> None:
        boom = ScraplingResult(html="", final_url="x", status_code=500, elapsed_seconds=0.1)
        with (
            patch.object(module.settings, "SCRAPLING_ENABLED", True),
            patch.object(module.settings, "SCRAPLING_CIRCUIT_FAILURE_THRESHOLD", 3),
            patch.object(url_guard, "resolve_hostname", return_value=["93.184.216.34"]),
        ):
            with patch.object(ScraplingClient, "_fetch_sync", return_value=boom):
                with self.assertRaises(ScraplingUnavailableError):
                    await self.client.scrape("https://example.com/jobs")
            with patch.object(ScraplingClient, "_fetch_sync", return_value=_ok()):
                await self.client.scrape("https://example.com/jobs")
        self.assertEqual(self.client._consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
