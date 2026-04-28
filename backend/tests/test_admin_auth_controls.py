import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth as auth_endpoint
from app.services import totp_service


class TestAdminAuthControls(unittest.IsolatedAsyncioTestCase):
    def test_verify_totp_accepts_valid_code(self) -> None:
        secret = "ABCDABCDABCDABCDABCD"
        code = totp_service._hotp(secret, 1, digits=8)  # noqa: SLF001
        self.assertTrue(
            totp_service.verify_totp(
                secret_base32=secret,
                code=code,
                at_time=30,
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

    async def test_reserved_admin_password_login_returns_verification_challenge(self) -> None:
        admin_user = SimpleNamespace(
            id="admin-user-id",
            email="ghoshankan005@gmail.com",
            hashed_password="hashed-password",
            is_admin=True,
            is_active=True,
            account_type="candidate",
        )
        form_data = SimpleNamespace(username="ghoshankan005@gmail.com", password="secret-password")
        unlocked = SimpleNamespace(locked=False)
        fake_user_model = SimpleNamespace(email=object(), find_one=AsyncMock(return_value=admin_user))

        with (
            patch("app.api.api_v1.endpoints.auth.settings.ADMIN_BOOTSTRAP_EMAIL", "ghoshankan005@gmail.com"),
            patch.object(auth_endpoint.auth_security_service, "check_lock", new=AsyncMock(return_value=unlocked)),
            patch.object(auth_endpoint.auth_security_service, "audit_event", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth.User", fake_user_model),
            patch("app.api.api_v1.endpoints.auth.verify_password", return_value=True),
            patch("app.api.api_v1.endpoints.auth._issue_admin_email_otp", new=AsyncMock(return_value=("debug", 60, "123456"))),
            patch("app.api.api_v1.endpoints.auth._create_admin_challenge_token", return_value="challenge-token"),
        ):
            payload = await auth_endpoint.login_access_token(form_data=form_data)

        self.assertTrue(payload.requires_admin_verification)
        self.assertEqual(payload.admin_challenge_token, "challenge-token")
        self.assertEqual(payload.admin_verification_path, "/control/auth")
        self.assertEqual(payload.debug_otp, "123456")

    async def test_admin_verify_uses_otp_and_totp_before_issuing_token(self) -> None:
        admin_user = SimpleNamespace(
            id="admin-user-id",
            email="ghoshankan005@gmail.com",
            is_admin=True,
            is_active=True,
            account_type="candidate",
        )
        unlocked = SimpleNamespace(locked=False)
        fake_user_model = SimpleNamespace(email=object(), find_one=AsyncMock(return_value=admin_user))
        payload = auth_endpoint.AdminVerifyRequest(
            email="ghoshankan005@gmail.com",
            otp="123456",
            totp_code="654321",
            admin_challenge_token="challenge-token",
        )

        with (
            patch("app.api.api_v1.endpoints.auth.settings.ADMIN_BOOTSTRAP_EMAIL", "ghoshankan005@gmail.com"),
            patch("app.api.api_v1.endpoints.auth._decode_admin_challenge_token", return_value="admin-user-id"),
            patch.object(auth_endpoint.auth_security_service, "check_lock", new=AsyncMock(return_value=unlocked)),
            patch.object(auth_endpoint.auth_security_service, "audit_event", new=AsyncMock()),
            patch.object(auth_endpoint.auth_security_service, "record_success", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth.User", fake_user_model),
            patch("app.api.api_v1.endpoints.auth.validate_otp", new=AsyncMock(return_value=True)),
            patch("app.api.api_v1.endpoints.auth.delete_otp", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth._validate_admin_totp_or_raise"),
            patch("app.api.api_v1.endpoints.auth.create_access_token", return_value="final-jwt"),
            patch("app.api.api_v1.endpoints.auth.auth_cookie_only_mode_enabled", return_value=False),
        ):
            result = await auth_endpoint.verify_admin_access_token(payload=payload)

        self.assertEqual(result["access_token"], "final-jwt")
        self.assertEqual(result["token_type"], "bearer")


if __name__ == "__main__":
    unittest.main()
