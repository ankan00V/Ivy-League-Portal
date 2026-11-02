import base64
import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth as auth_endpoint


def make_bridge_credential(payload: dict[str, object], secret: str) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


class TestNeonAuthBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "test-neon-bridge-secret"
        self.now = int(time.time())
        self.payload = {
            "aud": "vidyaverse-backend",
            "sub": "managed-user-id",
            "email": "student@example.edu",
            "name": "Test Student",
            "iat": self.now,
            "exp": self.now + 60,
        }

    def test_accepts_short_lived_credential_with_valid_signature(self) -> None:
        credential = make_bridge_credential(self.payload, self.secret)
        with patch.object(auth_endpoint.settings, "NEON_AUTH_BRIDGE_SECRET", self.secret):
            claims = auth_endpoint._decode_neon_bridge_credential(credential)

        self.assertEqual(str(claims.email), "student@example.edu")
        self.assertEqual(claims.sub, "managed-user-id")

    def test_rejects_tampered_or_expired_credentials(self) -> None:
        credential = make_bridge_credential(self.payload, self.secret)
        expired = {**self.payload, "iat": self.now - 180, "exp": self.now - 60}
        expired_credential = make_bridge_credential(expired, self.secret)

        with patch.object(auth_endpoint.settings, "NEON_AUTH_BRIDGE_SECRET", self.secret):
            with self.assertRaises(HTTPException) as tampered:
                auth_endpoint._decode_neon_bridge_credential(f"{credential}tampered")
            with self.assertRaises(HTTPException) as expired_error:
                auth_endpoint._decode_neon_bridge_credential(expired_credential)

        self.assertEqual(tampered.exception.status_code, 401)
        self.assertEqual(expired_error.exception.status_code, 401)

    def test_candidate_gmail_is_allowed_when_institutional_policy_is_disabled(self) -> None:
        with patch.object(auth_endpoint.settings, "CANDIDATE_REQUIRE_INSTITUTIONAL_EMAIL", False):
            auth_endpoint._ensure_candidate_institutional_email("student@gmail.com")
