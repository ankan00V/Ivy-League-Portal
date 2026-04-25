import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth as auth_endpoint


class TestAuthOAuth(unittest.IsolatedAsyncioTestCase):
    def test_normalize_frontend_origin_accepts_clean_origin(self) -> None:
        self.assertEqual(
            auth_endpoint._normalize_frontend_origin("https://web.test"),
            "https://web.test",
        )

    def test_normalize_frontend_origin_rejects_paths_and_queries(self) -> None:
        self.assertIsNone(auth_endpoint._normalize_frontend_origin("https://web.test/auth/callback"))
        self.assertIsNone(auth_endpoint._normalize_frontend_origin("https://web.test?x=1"))
        self.assertIsNone(auth_endpoint._normalize_frontend_origin("javascript:alert(1)"))

    def test_resolve_oauth_frontend_urls_uses_runtime_origin_with_configured_paths(self) -> None:
        with (
            patch.object(auth_endpoint.settings, "FRONTEND_OAUTH_SUCCESS_URL", "http://localhost:3000/auth/callback"),
            patch.object(auth_endpoint.settings, "FRONTEND_OAUTH_FAILURE_URL", "http://localhost:3000/login"),
        ):
            success_url, failure_url = auth_endpoint._resolve_oauth_frontend_urls("https://web.test")

        self.assertEqual(success_url, "https://web.test/auth/callback")
        self.assertEqual(failure_url, "https://web.test/login")

    def test_resolve_google_redirect_uri_switches_localhost_host_for_local_frontend(self) -> None:
        with patch.object(
            auth_endpoint.settings,
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://127.0.0.1:8000/api/v1/auth/oauth/google/callback",
        ):
            redirect_uri = auth_endpoint._resolve_google_redirect_uri("http://localhost:3000")

        self.assertEqual(redirect_uri, "http://localhost:8000/api/v1/auth/oauth/google/callback")

    def test_is_allowed_google_redirect_uri_accepts_localhost_variant(self) -> None:
        with patch.object(
            auth_endpoint.settings,
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://127.0.0.1:8000/api/v1/auth/oauth/google/callback",
        ):
            self.assertTrue(
                auth_endpoint._is_allowed_google_redirect_uri(
                    "http://localhost:8000/api/v1/auth/oauth/google/callback"
                )
            )

    def test_public_access_token_uses_cookie_sentinel_in_cookie_only_mode(self) -> None:
        with patch("app.api.api_v1.endpoints.auth.auth_cookie_only_mode_enabled", return_value=True):
            self.assertEqual(
                auth_endpoint._public_access_token("real-jwt-token"),
                auth_endpoint.COOKIE_SESSION_SENTINEL,
            )

    def test_public_access_token_keeps_token_when_cookie_only_mode_is_disabled(self) -> None:
        with patch("app.api.api_v1.endpoints.auth.auth_cookie_only_mode_enabled", return_value=False):
            self.assertEqual(
                auth_endpoint._public_access_token("real-jwt-token"),
                "real-jwt-token",
            )

    async def test_oauth_google_start_persists_frontend_origin_in_state(self) -> None:
        with (
            patch.object(auth_endpoint.settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id"),
            patch.object(auth_endpoint.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret"),
            patch.object(auth_endpoint.settings, "GOOGLE_OAUTH_REDIRECT_URI", "https://api.test/api/v1/auth/oauth/google/callback"),
        ):
            payload = await auth_endpoint.oauth_google_start(
                account_type="candidate",
                next="/auth/callback",
                frontend_origin="https://web.test",
            )

        redirect_url = payload["redirect_url"]
        state = parse_qs(urlsplit(redirect_url).query)["state"][0]
        decoded = auth_endpoint._base64url_decode(state)

        self.assertEqual(decoded["frontend_origin"], "https://web.test")
        self.assertEqual(decoded["account_type"], "candidate")
        self.assertEqual(decoded["next"], "/auth/callback")

    async def test_oauth_google_start_uses_localhost_redirect_uri_when_frontend_origin_is_localhost(self) -> None:
        with (
            patch.object(auth_endpoint.settings, "GOOGLE_OAUTH_CLIENT_ID", "client-id"),
            patch.object(auth_endpoint.settings, "GOOGLE_OAUTH_CLIENT_SECRET", "client-secret"),
            patch.object(
                auth_endpoint.settings,
                "GOOGLE_OAUTH_REDIRECT_URI",
                "http://127.0.0.1:8000/api/v1/auth/oauth/google/callback",
            ),
        ):
            payload = await auth_endpoint.oauth_google_start(
                account_type="candidate",
                next="/auth/callback",
                frontend_origin="http://localhost:3000",
            )

        redirect_url = payload["redirect_url"]
        query = parse_qs(urlsplit(redirect_url).query)
        self.assertEqual(
            query["redirect_uri"][0],
            "http://localhost:8000/api/v1/auth/oauth/google/callback",
        )

    async def test_oauth_google_callback_redirects_failures_back_to_origin(self) -> None:
        with (
            patch.object(auth_endpoint.settings, "FRONTEND_OAUTH_SUCCESS_URL", "http://localhost:3000/auth/callback"),
            patch.object(auth_endpoint.settings, "FRONTEND_OAUTH_FAILURE_URL", "http://localhost:3000/login"),
        ):
            state = auth_endpoint._base64url_encode(
                {
                    "account_type": "candidate",
                    "next": "/auth/callback",
                    "frontend_origin": "https://web.test",
                }
            )
            response = await auth_endpoint.oauth_google_callback(
                error="access_denied",
                state=state,
            )

        self.assertEqual(response.status_code, 302)
        location = response.headers["location"]
        self.assertTrue(location.startswith("https://web.test/login?"))
        self.assertIn("oauth_access_denied", location)

    async def test_send_otp_enforces_cooldown(self) -> None:
        request = auth_endpoint.OTPSendRequest(
            email="candidate@example.com",
            purpose="signup",
            account_type="candidate",
        )
        with (
            patch.object(auth_endpoint, "_validate_user_for_purpose", new=AsyncMock(return_value=None)),
            patch.object(auth_endpoint, "_normalize_account_type", return_value="candidate"),
            patch.object(auth_endpoint, "get_otp_cooldown_remaining", new=AsyncMock(return_value=42)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await auth_endpoint.send_otp(request)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("42", str(ctx.exception.detail))
        self.assertEqual((ctx.exception.headers or {}).get("Retry-After"), "42")

    async def test_send_otp_success_includes_cooldown_seconds(self) -> None:
        request = auth_endpoint.OTPSendRequest(
            email="candidate@example.com",
            purpose="signup",
            account_type="candidate",
        )
        with (
            patch.object(auth_endpoint.settings, "OTP_SEND_COOLDOWN_SECONDS", 60),
            patch.object(auth_endpoint, "_validate_user_for_purpose", new=AsyncMock(return_value=None)),
            patch.object(auth_endpoint, "_normalize_account_type", return_value="candidate"),
            patch.object(auth_endpoint, "get_otp_cooldown_remaining", new=AsyncMock(return_value=0)),
            patch.object(auth_endpoint, "set_otp", new=AsyncMock()) as mock_set_otp,
            patch.object(auth_endpoint, "send_email_otp", new=AsyncMock(return_value=True)) as mock_send_email_otp,
        ):
            response = await auth_endpoint.send_otp(request)

        self.assertEqual(response.delivery, "email")
        self.assertEqual(response.cooldown_seconds, 60)
        mock_set_otp.assert_awaited_once()
        mock_send_email_otp.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
