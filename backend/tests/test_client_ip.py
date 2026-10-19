import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.client_ip import client_ip
from app.core.config import settings


def _request(peer: str, forwarded: str | None = None) -> SimpleNamespace:
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


class TestClientIPTrustBoundary(unittest.TestCase):
    def test_untrusted_peer_cannot_spoof_x_forwarded_for(self) -> None:
        with patch.object(settings, "TRUSTED_PROXY_IPS", []):
            resolved = client_ip(_request("198.51.100.10", "10.10.2.4"))
        self.assertEqual(resolved, "198.51.100.10")

    def test_trusted_proxy_uses_the_closest_untrusted_forwarded_hop(self) -> None:
        with patch.object(settings, "TRUSTED_PROXY_IPS", ["10.0.0.0/8"]):
            resolved = client_ip(_request("10.0.0.15", "198.51.100.10, 10.0.0.8"))
        self.assertEqual(resolved, "198.51.100.10")

    def test_invalid_forwarded_chain_falls_back_to_the_trusted_peer(self) -> None:
        with patch.object(settings, "TRUSTED_PROXY_IPS", ["10.0.0.0/8"]):
            resolved = client_ip(_request("10.0.0.15", "198.51.100.10, forged"))
        self.assertEqual(resolved, "10.0.0.15")

    def test_untrusted_peer_address_is_not_replaced_by_unparseable_header(self) -> None:
        with patch.object(settings, "TRUSTED_PROXY_IPS", []):
            resolved = client_ip(_request("2001:db8::10", "not-an-ip"))
        self.assertEqual(resolved, "2001:db8::10")


if __name__ == "__main__":
    unittest.main()
