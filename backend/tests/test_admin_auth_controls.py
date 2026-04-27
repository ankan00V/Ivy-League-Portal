import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth as auth_endpoint
from app.services import totp_service


class TestAdminAuthControls(unittest.IsolatedAsyncioTestCase):
    def test_verify_totp_accepts_rfc_vector(self) -> None:
        # RFC 6238 test vector (SHA1, 30s step, 8 digits) at T=59.
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertTrue(
            totp_service.verify_totp(
                secret_base32=secret,
                code="94287082",
                at_time=59,
                period_seconds=30,
                digits=8,
                window_steps=0,
            )
        )

    def test_encrypt_decrypt_totp_secret_roundtrip(self) -> None:
        secret = "JBSWY3DPEHPK3PXP"
        encrypted = totp_service.encrypt_secret(secret)
        self.assertNotEqual(encrypted, secret)
        self.assertEqual(totp_service.decrypt_secret(encrypted), secret)

    async def test_reserved_admin_identity_is_blocked_from_public_otp_flow(self) -> None:
        with patch("app.api.api_v1.endpoints.auth.settings.ADMIN_BOOTSTRAP_EMAIL", "ghoshankan005@gmail.com"):
            with self.assertRaises(HTTPException) as ctx:
                await auth_endpoint._validate_user_for_purpose("ghoshankan005@gmail.com", "signin")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_scopes_for_user_only_grants_admin_scopes_for_reserved_identity(self) -> None:
        with patch("app.api.api_v1.endpoints.auth.settings.ADMIN_BOOTSTRAP_EMAIL", "ghoshankan005@gmail.com"):
            reserved_admin = SimpleNamespace(is_admin=True, email="ghoshankan005@gmail.com")
            shadow_admin = SimpleNamespace(is_admin=True, email="someoneelse@example.com")
            reserved_scopes = auth_endpoint._scopes_for_user(reserved_admin)
            shadow_scopes = auth_endpoint._scopes_for_user(shadow_admin)
        self.assertIn("admin", reserved_scopes)
        self.assertNotIn("admin", shadow_scopes)


if __name__ == "__main__":
    unittest.main()
