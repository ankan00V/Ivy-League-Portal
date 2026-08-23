"""Resend transport for OTP mail.

Context: OTP mail was going out over Gmail SMTP from a consumer @gmail.com
address. Verified sends were accepted by Gmail (2.0.0 OK, real queue id) and
still never reached a college inbox, because candidate signup requires an
institutional address and those domains sit behind Microsoft 365, which filters
consumer senders hard. Resend sends from a domain we DKIM-sign ourselves.

The tests below are mostly about one property: a delivery is only ever reported
as successful when the provider actually confirmed it. This repo has a history of
jobs reporting success for work that silently did nothing, and auth mail is the
worst possible place for that -- a fabricated "sent" strands a real user at a
verification screen with no code coming.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services import email as email_mod


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient as an async context manager."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self._error:
            raise self._error
        return self._response


class TestResendDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_returns_message_id_on_success(self) -> None:
        client = _FakeAsyncClient(_FakeResponse(200, {"id": "msg_abc123"}))
        with (
            patch.object(settings, "RESEND_API_KEY", "re_test_key"),
            patch.object(email_mod.httpx, "AsyncClient", lambda **kw: client),
        ):
            message_id = await email_mod._deliver_via_resend(
                to_email="student@lpu.in",
                subject="s",
                text_body="t",
                html_body="<p>h</p>",
            )
        self.assertEqual(message_id, "msg_abc123")
        self.assertEqual(len(client.calls), 1)
        sent = client.calls[0]
        self.assertTrue(sent["url"].endswith("/emails"))
        self.assertEqual(sent["json"]["to"], ["student@lpu.in"])
        self.assertEqual(sent["headers"]["Authorization"], "Bearer re_test_key")
        # Both parts must survive; a text-only auth mail looks like phishing to
        # the very filters this change exists to get past.
        self.assertEqual(sent["json"]["text"], "t")
        self.assertEqual(sent["json"]["html"], "<p>h</p>")

    async def test_success_without_message_id_is_a_failure(self) -> None:
        # The important one. A 200 carrying no id must not read as delivered.
        client = _FakeAsyncClient(_FakeResponse(200, {"ok": True}))
        with (
            patch.object(settings, "RESEND_API_KEY", "re_test_key"),
            patch.object(email_mod.httpx, "AsyncClient", lambda **kw: client),
        ):
            with self.assertRaises(RuntimeError) as caught:
                await email_mod._deliver_via_resend(
                    to_email="student@lpu.in", subject="s", text_body="t", html_body="h"
                )
        self.assertIn("without returning a message id", str(caught.exception))

    async def test_http_error_raises(self) -> None:
        client = _FakeAsyncClient(_FakeResponse(403, None, "domain not verified"))
        with (
            patch.object(settings, "RESEND_API_KEY", "re_test_key"),
            patch.object(email_mod.httpx, "AsyncClient", lambda **kw: client),
        ):
            with self.assertRaises(RuntimeError) as caught:
                await email_mod._deliver_via_resend(
                    to_email="student@lpu.in", subject="s", text_body="t", html_body="h"
                )
        self.assertIn("403", str(caught.exception))

    async def test_missing_api_key_raises(self) -> None:
        with patch.object(settings, "RESEND_API_KEY", ""):
            with self.assertRaises(RuntimeError) as caught:
                await email_mod._deliver_via_resend(
                    to_email="student@lpu.in", subject="s", text_body="t", html_body="h"
                )
        self.assertIn("RESEND_API_KEY", str(caught.exception))


class TestSendEmailOtpRouting(unittest.IsolatedAsyncioTestCase):
    async def test_provider_resend_does_not_touch_smtp(self) -> None:
        deliver = AsyncMock(return_value="msg_1")
        smtp = AsyncMock()
        with (
            patch.object(settings, "EMAIL_PROVIDER", "resend"),
            patch.object(email_mod, "_deliver_via_resend", deliver),
            patch.object(email_mod.aiosmtplib, "send", smtp),
        ):
            result = await email_mod.send_email_otp("student@lpu.in", "123456")
        self.assertTrue(result)
        deliver.assert_awaited_once()
        smtp.assert_not_awaited()

    async def test_provider_smtp_does_not_touch_resend(self) -> None:
        deliver = AsyncMock(return_value="msg_1")
        smtp = AsyncMock(return_value=({}, "2.0.0 OK"))
        with (
            patch.object(settings, "EMAIL_PROVIDER", "smtp"),
            patch.object(settings, "SMTP_SERVER", "smtp.example.com"),
            # Pin credentials too. These were inherited from the developer's .env
            # until the Gmail block was commented out, at which point the SMTP
            # branch started failing its own config validation before reaching
            # the transport. Tests must not depend on ambient config.
            patch.object(settings, "SMTP_REQUIRE_AUTH", True),
            patch.object(settings, "SMTP_USER", "mailer@example.com"),
            patch.object(settings, "SMTP_PASSWORD", "secret"),
            patch.object(settings, "SMTP_USE_TLS", False),
            patch.object(settings, "SMTP_STARTTLS", True),
            patch.object(email_mod, "_deliver_via_resend", deliver),
            patch.object(email_mod.aiosmtplib, "send", smtp),
        ):
            result = await email_mod.send_email_otp("student@lpu.in", "123456")
        self.assertTrue(result)
        smtp.assert_awaited()
        deliver.assert_not_awaited()

    async def test_resend_failure_propagates_so_caller_can_502(self) -> None:
        # send_otp turns this into a 502 and deletes the stored OTP. If it were
        # swallowed the user would see "sent" for mail that never left.
        deliver = AsyncMock(side_effect=RuntimeError("resend down"))
        with (
            patch.object(settings, "EMAIL_PROVIDER", "resend"),
            patch.object(settings, "OTP_EMAIL_MAX_RETRIES", 1),
            patch.object(email_mod, "_deliver_via_resend", deliver),
        ):
            with self.assertRaises(RuntimeError):
                await email_mod.send_email_otp("student@lpu.in", "123456")

    async def test_resend_retries_then_succeeds(self) -> None:
        deliver = AsyncMock(side_effect=[RuntimeError("transient"), "msg_2"])
        with (
            patch.object(settings, "EMAIL_PROVIDER", "resend"),
            patch.object(settings, "OTP_EMAIL_MAX_RETRIES", 3),
            patch.object(email_mod, "_deliver_via_resend", deliver),
            patch.object(email_mod.asyncio, "sleep", AsyncMock()),
        ):
            result = await email_mod.send_email_otp("student@lpu.in", "123456")
        self.assertTrue(result)
        self.assertEqual(deliver.await_count, 2)


if __name__ == "__main__":
    unittest.main()
