import sys
import ipaddress
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import url_guard
from app.core.url_guard import BlockedTargetURL, PinnedPublicTransport, assert_public_http_url, is_public_http_url


class TestUrlGuardBlocksSSRF(unittest.TestCase):
    """Guards server-side fetches of user-supplied source URLs.

    Reproduced before this existed: POST /api/v1/sources/submit with
    http://169.254.169.254/latest/meta-data/ returned 200 and the qualification
    pipeline fetched cloud instance metadata; http://10.0.0.5:8080/ turned the
    same pipeline into an internal port scanner, with reachability handed back
    to the submitter via GET /sources/my-submissions.
    """

    def test_blocks_cloud_metadata_endpoint(self) -> None:
        with self.assertRaises(BlockedTargetURL):
            assert_public_http_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_loopback_and_private_ranges(self) -> None:
        for url in (
            "http://127.0.0.1:8010/health",
            "http://10.0.0.5:8080/internal",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://[::1]/",
            "http://0.0.0.0/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))

    def test_blocks_internal_hostnames(self) -> None:
        for url in (
            "http://localhost/admin",
            "http://metadata.google.internal/",
            "http://db.internal/",
            "http://printer.local/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))

    def test_blocks_non_http_schemes(self) -> None:
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/", "redis://127.0.0.1:6379"):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))

    def test_blocks_embedded_credentials(self) -> None:
        self.assertFalse(is_public_http_url("http://user:pass@example.com/"))

    def test_blocks_hostname_resolving_to_private_address(self) -> None:
        """The decisive case: DNS is attacker-controlled for their own domain.

        A literal-IP-only check (which the render clients still use on their own)
        lets evil.example through when it answers with a link-local address.
        """
        with patch.object(url_guard, "resolve_hostname", return_value=["169.254.169.254"]):
            with self.assertRaises(BlockedTargetURL):
                assert_public_http_url("https://evil.example/payload")

    def test_blocks_when_any_resolved_address_is_private(self) -> None:
        with patch.object(
            url_guard, "resolve_hostname", return_value=["93.184.216.34", "127.0.0.1"]
        ):
            self.assertFalse(is_public_http_url("https://split-horizon.example/"))

    def test_allows_ordinary_public_sources(self) -> None:
        with patch.object(url_guard, "resolve_hostname", return_value=["93.184.216.34"]):
            for url in (
                "https://tensorhack.com/jobs",
                "https://internshala.com/internships",
                "http://careers.example.com/students",
            ):
                with self.subTest(url=url):
                    self.assertEqual(assert_public_http_url(url), url)

    def test_unresolvable_host_is_blocked_not_allowed(self) -> None:
        """Fails closed. An unresolvable host must not be treated as public."""
        with patch.object(url_guard, "resolve_hostname", side_effect=OSError("nxdomain")):
            with self.assertRaises(BlockedTargetURL):
                assert_public_http_url("https://does-not-exist.example/")


class TestPinnedPublicTransport(unittest.IsolatedAsyncioTestCase):
    async def test_pins_the_socket_to_the_validated_address(self) -> None:
        import httpx

        captured: dict[str, object] = {}

        async def parent_transport(_self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["host"] = request.headers.get("host")
            captured["sni"] = request.extensions.get("sni_hostname")
            return httpx.Response(200)

        with (
            patch.object(url_guard, "public_addresses_for", return_value=[ipaddress.ip_address("93.184.216.34")]),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", new=parent_transport),
        ):
            await PinnedPublicTransport().handle_async_request(httpx.Request("GET", "https://example.com/jobs"))

        self.assertIn("93.184.216.34", str(captured["url"]))
        self.assertEqual(captured["host"], "example.com")
        self.assertEqual(captured["sni"], "example.com")

    async def test_blocked_address_never_reaches_the_socket(self) -> None:
        import httpx

        with patch.object(
            url_guard,
            "public_addresses_for",
            side_effect=BlockedTargetURL("target_address_forbidden"),
        ), patch.object(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            new=AsyncMock(),
        ) as parent_transport:
            with self.assertRaises(BlockedTargetURL):
                await PinnedPublicTransport().handle_async_request(httpx.Request("GET", "https://evil.example/"))

        parent_transport.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
