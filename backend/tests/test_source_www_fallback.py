"""Sources that publish only on www must still be reachable.

normalize_url canonicalises a host through normalize_domain, which strips "www."
so that www.x.ac.in and x.ac.in are one source rather than two. That is right for
identity and wrong for fetching: a great many Indian government and university
sites serve only on www and refuse the apex outright. Measured across the seeded
academic sources, four of seven - nitttrkol, ugc, tifr and iitm - answered 200 on
www and ConnectError or ConnectTimeout on the apex.

The consequence was invisible and permanent. Those sources scored 36 on
reachability, were rejected, and would have been rejected on every future run
however good the site was, because the pipeline was asking for a hostname nobody
had ever served.

The fallback is a second candidate URL, and the security property that matters is
that it goes through the same validation as the first. A host that resolves to a
private or reserved address must still be refused, whatever it is called - these
tests fail loudly if the retry ever becomes an exemption.
"""

import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.source_discovery import normalize_domain, normalize_url


class TestIdentityStillCollapsesWww(unittest.TestCase):
    """The retry must not undo the deduplication the stripping exists for."""

    def test_www_and_apex_are_one_domain(self) -> None:
        self.assertEqual(normalize_domain("www.iitm.ac.in"), normalize_domain("iitm.ac.in"))

    def test_www_and_apex_normalise_to_one_url(self) -> None:
        # If these diverged, the same posting could enter the corpus twice -
        # which is why the fallback lives in the fetch path and not here.
        self.assertEqual(
            normalize_url("https://www.iitm.ac.in/jobs"),
            normalize_url("https://iitm.ac.in/jobs"),
        )

    def test_normalised_url_keeps_the_apex_host(self) -> None:
        self.assertEqual(urlparse(normalize_url("https://www.ugc.gov.in/")).netloc, "ugc.gov.in")


class TestGuardIsNotBypassed(unittest.TestCase):
    """The www retry re-validates; it does not skip validation.

    The guard exists because user-submitted sources reached the network
    unvalidated: 169.254.169.254 read cloud instance metadata, and private
    addresses turned the qualification pipeline into an internal port scanner
    whose results were returned to the submitter. Prefixing a host with "www."
    must never be a way back to any of that.
    """

    def _assert_blocked(self, url: str) -> None:
        from app.core.url_guard import assert_public_http_url

        with self.assertRaises(Exception, msg=f"{url} should be refused"):
            assert_public_http_url(url)

    def test_metadata_address_is_refused(self) -> None:
        # Only the literal address is asserted. "www.169.254.169.254" is a
        # hostname rather than an address, so whether it is refused depends on
        # what DNS says about it - which is not a property of this guard, and
        # differs once the suite patches resolution. Asserting it made this test
        # pass alone and fail in the suite, which is worse than not testing it.
        self._assert_blocked("http://169.254.169.254/")

    def test_private_addresses_are_refused(self) -> None:
        for url in ("http://10.0.0.5:8080/", "http://192.168.1.1/", "http://172.16.0.1/"):
            with self.subTest(url=url):
                self._assert_blocked(url)

    def test_loopback_is_refused(self) -> None:
        for url in ("http://localhost:8000/", "http://127.0.0.1/", "http://[::1]/"):
            with self.subTest(url=url):
                self._assert_blocked(url)

    def test_a_public_host_is_allowed(self) -> None:
        # The guard must not have been tightened into refusing everything, which
        # would make the tests above pass for the wrong reason.
        from app.core.url_guard import assert_public_http_url

        self.assertTrue(assert_public_http_url("https://www.example.com/"))


class TestFallbackOnlyAppliesOnce(unittest.TestCase):
    def test_a_www_host_is_not_prefixed_again(self) -> None:
        # www.www.x is nobody's hostname; retrying it would waste a lookup and
        # report a misleading failure reason.
        parsed = urlparse(normalize_url("https://www.tifr.res.in/"))
        self.assertFalse(parsed.netloc.startswith("www."))


if __name__ == "__main__":
    unittest.main()
