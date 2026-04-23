import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import smtp_from_email_value
from app.services import email as email_service


class TestEmailConfigResolution(unittest.TestCase):
    def test_smtp_from_email_prefers_auth_alias_over_placeholder_default(self) -> None:
        with (
            patch.object(email_service.settings, "SMTP_FROM_EMAIL", "noreply@vidyaverse.com"),
            patch.object(email_service.settings, "AUTH_OTP_FROM_EMAIL", "digitantra.helpdesk@gmail.com"),
        ):
            resolved = smtp_from_email_value()

        self.assertEqual(resolved, "digitantra.helpdesk@gmail.com")

    def test_smtp_from_email_keeps_explicit_sender(self) -> None:
        with (
            patch.object(email_service.settings, "SMTP_FROM_EMAIL", "otp@vidyaverse.com"),
            patch.object(email_service.settings, "AUTH_OTP_FROM_EMAIL", "digitantra.helpdesk@gmail.com"),
        ):
            resolved = smtp_from_email_value()

        self.assertEqual(resolved, "otp@vidyaverse.com")


class TestEmailDeliveryRetries(unittest.IsolatedAsyncioTestCase):
    async def test_send_email_otp_retries_then_succeeds(self) -> None:
        with (
            patch.object(email_service.settings, "SMTP_SERVER", "smtp.gmail.com"),
            patch.object(email_service.settings, "SMTP_HOST", "smtp.gmail.com"),
            patch.object(email_service.settings, "SMTP_PORT", 587),
            patch.object(email_service.settings, "SMTP_STARTTLS", True),
            patch.object(email_service.settings, "SMTP_USE_TLS", False),
            patch.object(email_service.settings, "SMTP_TIMEOUT_SECONDS", 10.0),
            patch.object(email_service.settings, "SMTP_REQUIRE_AUTH", True),
            patch.object(email_service.settings, "SMTP_USER", "mailer@example.com"),
            patch.object(email_service.settings, "SMTP_PASSWORD", "secret"),
            patch.object(email_service.settings, "SMTP_FROM_EMAIL", "mailer@example.com"),
            patch.object(email_service.settings, "SMTP_FROM_NAME", "VidyaVerse"),
            patch.object(email_service.settings, "OTP_EMAIL_MAX_RETRIES", 3),
            patch("app.services.email.aiosmtplib.send", new=AsyncMock(side_effect=[RuntimeError("temp"), True])) as mock_send,
            patch("app.services.email.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        ):
            delivered = await email_service.send_email_otp("student@example.com", "123456")

        self.assertTrue(delivered)
        self.assertEqual(mock_send.await_count, 2)
        self.assertEqual(mock_sleep.await_count, 1)

    async def test_send_email_otp_raises_after_max_retries(self) -> None:
        with (
            patch.object(email_service.settings, "SMTP_SERVER", "smtp.gmail.com"),
            patch.object(email_service.settings, "SMTP_HOST", "smtp.gmail.com"),
            patch.object(email_service.settings, "SMTP_PORT", 587),
            patch.object(email_service.settings, "SMTP_STARTTLS", True),
            patch.object(email_service.settings, "SMTP_USE_TLS", False),
            patch.object(email_service.settings, "SMTP_TIMEOUT_SECONDS", 10.0),
            patch.object(email_service.settings, "SMTP_REQUIRE_AUTH", True),
            patch.object(email_service.settings, "SMTP_USER", "mailer@example.com"),
            patch.object(email_service.settings, "SMTP_PASSWORD", "secret"),
            patch.object(email_service.settings, "SMTP_FROM_EMAIL", "mailer@example.com"),
            patch.object(email_service.settings, "SMTP_FROM_NAME", "VidyaVerse"),
            patch.object(email_service.settings, "OTP_EMAIL_MAX_RETRIES", 2),
            patch("app.services.email.aiosmtplib.send", new=AsyncMock(side_effect=RuntimeError("down"))) as mock_send,
            patch("app.services.email.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        ):
            with self.assertRaises(RuntimeError):
                await email_service.send_email_otp("student@example.com", "123456")

        self.assertEqual(mock_send.await_count, 2)
        self.assertEqual(mock_sleep.await_count, 1)


if __name__ == "__main__":
    unittest.main()
