"""The liveness sweep fetches whatever URLs the corpus happens to hold.

It runs unattended every few hours against rows that came from automatically
discovered sources, so the address is untrusted input even though no person
typed it. `source_discovery` already resolves and checks its own targets before
fetching; the liveness sweep reached arbitrary stored URLs without that, which
made it a blind server-side request forgery primitive: alive/dead is a boolean
oracle about whatever the server can reach, including loopback, RFC1918 and the
cloud metadata address.

Following redirects reopened the same hole from the other side. A perfectly
public URL can answer with a 302 to 169.254.169.254, and a check that follows
it has handed the decision back to the remote host.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.opportunity_status_service import OpportunityStatusService


def _row(url):
    return SimpleNamespace(url=url)


class SsrfGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = OpportunityStatusService()

    async def _check(self, url):
        """Fails the test if any HTTP call is attempted."""
        with patch(
            "app.services.opportunity_status_service.httpx.AsyncClient",
            side_effect=AssertionError(f"network call attempted for {url}"),
        ):
            return await self.service.check_url_liveness(_row(url))

    async def test_the_cloud_metadata_address_is_never_fetched(self):
        self.assertEqual(await self._check("http://169.254.169.254/latest/meta-data/"), "unknown")

    async def test_loopback_is_never_fetched(self):
        for url in ("http://127.0.0.1:8011/health", "http://localhost/admin"):
            self.assertEqual(await self._check(url), "unknown", url)

    async def test_private_ranges_are_never_fetched(self):
        for url in ("http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.9/"):
            self.assertEqual(await self._check(url), "unknown", url)

    async def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://example.com/"):
            self.assertEqual(await self._check(url), "unknown", url)

    async def test_a_blocked_target_is_unknown_not_dead(self):
        """"Dead" retires a listing. A URL that was never contacted has not
        earned that verdict, and only 404/410 may retire a row."""
        self.assertNotEqual(await self._check("http://169.254.169.254/"), "dead")


class RedirectTests(unittest.IsolatedAsyncioTestCase):
    """A public URL that answers 302 to an internal one must not be followed."""

    def setUp(self):
        self.service = OpportunityStatusService()

    async def test_redirects_are_not_followed(self):
        captured = {}

        class _FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def head(self, url):
                return SimpleNamespace(status_code=302)

        with patch("app.services.opportunity_status_service.httpx.AsyncClient", _FakeClient):
            verdict = await self.service.check_url_liveness(_row("https://example.com/job/1"))

        self.assertFalse(captured.get("follow_redirects"))
        # A 3xx still means the posting resolved to something.
        self.assertEqual(verdict, "alive")

    async def test_a_public_url_is_still_checked(self):
        """The guard must not block the ordinary case it exists to allow."""

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def head(self, url):
                return SimpleNamespace(status_code=404)

        with patch("app.services.opportunity_status_service.httpx.AsyncClient", _FakeClient):
            verdict = await self.service.check_url_liveness(_row("https://example.com/job/gone"))
        self.assertEqual(verdict, "dead")


if __name__ == "__main__":
    unittest.main()


class RebindingTests(unittest.IsolatedAsyncioTestCase):
    """The pre-flight check resolves the name; httpx resolves it again to
    connect. A hostile resolver can answer differently each time, so the peer
    is re-checked from the socket after connecting."""

    def setUp(self):
        self.service = OpportunityStatusService()

    def _client_with_peer(self, peer):
        class _Stream:
            @staticmethod
            def get_extra_info(key):
                return peer if key == "server_addr" else None

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def head(self, url):
                return SimpleNamespace(
                    status_code=200, extensions={"network_stream": _Stream()}
                )

        return _FakeClient

    async def test_a_connection_that_lands_on_metadata_is_discarded(self):
        with patch(
            "app.services.opportunity_status_service.httpx.AsyncClient",
            self._client_with_peer(("169.254.169.254", 80)),
        ):
            verdict = await self.service.check_url_liveness(_row("https://example.com/job/1"))
        self.assertEqual(verdict, "unknown")

    async def test_a_connection_that_lands_on_loopback_is_discarded(self):
        with patch(
            "app.services.opportunity_status_service.httpx.AsyncClient",
            self._client_with_peer(("127.0.0.1", 8011)),
        ):
            self.assertEqual(
                await self.service.check_url_liveness(_row("https://example.com/job/1")), "unknown"
            )

    async def test_a_public_peer_is_accepted(self):
        with patch(
            "app.services.opportunity_status_service.httpx.AsyncClient",
            self._client_with_peer(("93.184.216.34", 443)),
        ):
            self.assertEqual(
                await self.service.check_url_liveness(_row("https://example.com/job/1")), "alive"
            )

    async def test_a_transport_without_socket_info_is_not_penalised(self):
        """Defence in depth on top of the pre-flight check, not a reason to
        fail every check when the extension is absent."""

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def head(self, url):
                return SimpleNamespace(status_code=200, extensions={})

        with patch("app.services.opportunity_status_service.httpx.AsyncClient", _FakeClient):
            self.assertEqual(
                await self.service.check_url_liveness(_row("https://example.com/job/1")), "alive"
            )


class PinnedTransportTests(unittest.IsolatedAsyncioTestCase):
    """Checking a hostname and then letting the client resolve it again leaves
    a window a hostile resolver can walk through. The transport removes the
    second lookup instead of racing it."""

    async def _send(self, url, addresses):
        import httpx

        from app.services.opportunity_status_service import PinnedPublicTransport

        captured = {}

        async def _parent(self, request):
            captured["url"] = str(request.url)
            captured["host_header"] = request.headers.get("Host")
            captured["sni"] = (request.extensions or {}).get("sni_hostname")
            return httpx.Response(200)

        with (
            patch(
                "app.services.opportunity_status_service.public_addresses_for",
                return_value=addresses,
            ),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _parent),
        ):
            await PinnedPublicTransport().handle_async_request(
                httpx.Request("HEAD", url)
            )
        return captured

    async def test_the_connection_goes_to_the_validated_address(self):
        import ipaddress

        sent = await self._send(
            "https://example.com/job/1", [ipaddress.ip_address("93.184.216.34")]
        )
        self.assertIn("93.184.216.34", sent["url"])
        self.assertNotIn("example.com", sent["url"])

    async def test_the_original_hostname_survives_for_tls_and_routing(self):
        """Connecting by IP without this fails certificate verification for
        every ordinary listing, and virtual hosts serve the wrong site."""
        import ipaddress

        sent = await self._send(
            "https://example.com/job/1", [ipaddress.ip_address("93.184.216.34")]
        )
        self.assertEqual(sent["sni"], "example.com")
        self.assertEqual(sent["host_header"], "example.com")

    async def test_ipv4_is_preferred_when_both_resolve(self):
        import ipaddress

        sent = await self._send(
            "https://example.com/x",
            [ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"), ipaddress.ip_address("93.184.216.34")],
        )
        self.assertIn("93.184.216.34", sent["url"])

    async def test_a_blocked_host_never_reaches_the_socket(self):
        import httpx

        from app.core.url_guard import BlockedTargetURL
        from app.services.opportunity_status_service import PinnedPublicTransport

        with (
            patch(
                "app.services.opportunity_status_service.public_addresses_for",
                side_effect=BlockedTargetURL("target_address_forbidden:169.254.169.254"),
            ),
            patch.object(
                httpx.AsyncHTTPTransport,
                "handle_async_request",
                AsyncMock(side_effect=AssertionError("socket opened for a blocked target")),
            ),
        ):
            with self.assertRaises(BlockedTargetURL):
                await PinnedPublicTransport().handle_async_request(
                    httpx.Request("HEAD", "https://evil.example/x")
                )
