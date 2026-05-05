import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth


class TestOtpDeliveryBehavior(unittest.IsolatedAsyncioTestCase):
    async def test_local_smtp_failure_returns_debug_otp_when_fallback_enabled(self) -> None:
        request = auth.OTPSendRequest(
            email="student@example.com",
            purpose="signup",
            account_type="candidate",
        )

        with (
            patch.object(auth.settings, "ENVIRONMENT", "local"),
            patch.object(auth.settings, "OTP_ALLOW_DEBUG_FALLBACK", True),
            patch.object(auth.settings, "OTP_SEND_COOLDOWN_SECONDS", 60),
            patch.object(auth.secrets, "randbelow", return_value=123456),
            patch.object(auth, "_validate_user_for_purpose", new=AsyncMock(return_value=None)),
            patch.object(auth, "get_otp_cooldown_remaining", new=AsyncMock(return_value=0)),
            patch.object(auth, "set_otp", new=AsyncMock()) as set_otp,
            patch.object(auth, "send_email_otp", new=AsyncMock(side_effect=RuntimeError("smtp rejected"))),
            patch.object(auth.auth_security_service, "audit_event", new=AsyncMock()),
        ):
            response = await auth.send_otp(request)

        self.assertEqual(response.delivery, "debug")
        self.assertEqual(response.debug_otp, "123456")
        set_otp.assert_awaited_once()

    async def test_production_smtp_failure_deletes_otp_and_fails_closed(self) -> None:
        request = auth.OTPSendRequest(
            email="student@example.com",
            purpose="signup",
            account_type="candidate",
        )

        with (
            patch.object(auth.settings, "ENVIRONMENT", "production"),
            patch.object(auth.settings, "OTP_ALLOW_DEBUG_FALLBACK", True),
            patch.object(auth.settings, "OTP_SEND_COOLDOWN_SECONDS", 60),
            patch.object(auth.secrets, "randbelow", return_value=123456),
            patch.object(auth, "_validate_user_for_purpose", new=AsyncMock(return_value=None)),
            patch.object(auth, "get_otp_cooldown_remaining", new=AsyncMock(return_value=0)),
            patch.object(auth, "set_otp", new=AsyncMock()),
            patch.object(auth, "delete_otp", new=AsyncMock()) as delete_otp,
            patch.object(auth, "send_email_otp", new=AsyncMock(side_effect=RuntimeError("smtp rejected"))),
            patch.object(auth.auth_security_service, "audit_event", new=AsyncMock()),
        ):
            with self.assertRaises(HTTPException) as raised:
                await auth.send_otp(request)

        self.assertEqual(raised.exception.status_code, 502)
        delete_otp.assert_awaited_once_with("student@example.com", purpose="signup")


if __name__ == "__main__":
    unittest.main()
