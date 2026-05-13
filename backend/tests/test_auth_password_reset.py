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


class TestForgotPasswordFlow(unittest.IsolatedAsyncioTestCase):
    async def test_password_reset_updates_hash_after_valid_otp(self) -> None:
        user = SimpleNamespace(
            id="user-id",
            email="student@example.com",
            account_type="candidate",
            auth_provider="otp",
            hashed_password="OTP_NO_PASSWORD",
            is_admin=False,
            save=AsyncMock(),
        )
        fake_user_model = SimpleNamespace(email=object(), find_one=AsyncMock(return_value=user))
        payload = auth_endpoint.ForgotPasswordResetRequest(
            email="student@example.com",
            otp="123456",
            password="StrongPass1",
            confirm_password="StrongPass1",
            account_type="candidate",
        )
        unlocked = SimpleNamespace(locked=False)

        with (
            patch("app.api.api_v1.endpoints.auth.User", fake_user_model),
            patch.object(auth_endpoint.auth_security_service, "check_lock", new=AsyncMock(return_value=unlocked)),
            patch.object(auth_endpoint.auth_security_service, "record_success", new=AsyncMock()),
            patch.object(auth_endpoint.auth_security_service, "audit_event", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth.validate_otp", new=AsyncMock(return_value=True)),
            patch("app.api.api_v1.endpoints.auth.delete_otp", new=AsyncMock()) as delete_otp,
            patch("app.api.api_v1.endpoints.auth.get_password_hash", return_value="hashed-new-password"),
        ):
            response = await auth_endpoint.reset_forgotten_password(payload=payload)

        self.assertIn("Password reset successfully", response.message)
        self.assertEqual(user.hashed_password, "hashed-new-password")
        self.assertEqual(user.auth_provider, "password")
        user.save.assert_awaited_once()
        delete_otp.assert_awaited_once_with("student@example.com", purpose="password_reset")

    async def test_password_reset_rejects_invalid_otp(self) -> None:
        user = SimpleNamespace(
            id="user-id",
            email="student@example.com",
            account_type="candidate",
            is_admin=False,
        )
        fake_user_model = SimpleNamespace(email=object(), find_one=AsyncMock(return_value=user))
        payload = auth_endpoint.ForgotPasswordResetRequest(
            email="student@example.com",
            otp="123456",
            password="StrongPass1",
            confirm_password="StrongPass1",
            account_type="candidate",
        )
        unlocked = SimpleNamespace(locked=False)
        failure = SimpleNamespace(locked=False, lock_until=None)

        with (
            patch("app.api.api_v1.endpoints.auth.User", fake_user_model),
            patch.object(auth_endpoint.auth_security_service, "check_lock", new=AsyncMock(return_value=unlocked)),
            patch.object(auth_endpoint.auth_security_service, "record_failure", new=AsyncMock(return_value=failure)),
            patch.object(auth_endpoint.auth_security_service, "audit_event", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth.validate_otp", new=AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await auth_endpoint.reset_forgotten_password(payload=payload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Invalid or expired OTP")

    async def test_password_reset_otp_send_uses_turnstile_for_public_users(self) -> None:
        request = auth_endpoint.ForgotPasswordSendRequest(
            email="student@example.com",
            account_type="candidate",
            turnstile_token="token",
        )
        user = SimpleNamespace(
            id="user-id",
            email="student@example.com",
            account_type="candidate",
            is_admin=False,
        )
        fake_user_model = SimpleNamespace(email=object(), find_one=AsyncMock(return_value=user))

        with (
            patch.object(auth_endpoint.settings, "TURNSTILE_ENABLED", True),
            patch.object(auth_endpoint, "_turnstile_is_verified", return_value=True) as verify_turnstile,
            patch.object(auth_endpoint.settings, "OTP_SEND_COOLDOWN_SECONDS", 60),
            patch.object(auth_endpoint.secrets, "randbelow", return_value=123456),
            patch("app.api.api_v1.endpoints.auth.User", fake_user_model),
            patch("app.api.api_v1.endpoints.auth.get_otp_cooldown_remaining", new=AsyncMock(return_value=0)),
            patch("app.api.api_v1.endpoints.auth.set_otp", new=AsyncMock()),
            patch("app.api.api_v1.endpoints.auth.send_email_otp", new=AsyncMock()),
            patch.object(auth_endpoint.auth_security_service, "audit_event", new=AsyncMock()),
        ):
            response = await auth_endpoint.send_password_reset_otp(request)

        self.assertEqual(response.delivery, "email")
        verify_turnstile.assert_called_once()


class TestTurnstileVerification(unittest.TestCase):
    def test_turnstile_skips_when_disabled(self) -> None:
        with patch.object(auth_endpoint.settings, "TURNSTILE_ENABLED", False):
            auth_endpoint._verify_turnstile_or_raise(None)

    def test_turnstile_requires_token_when_enabled(self) -> None:
        with patch.object(auth_endpoint.settings, "TURNSTILE_ENABLED", True):
            with self.assertRaises(HTTPException) as raised:
                auth_endpoint._verify_turnstile_or_raise("")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
