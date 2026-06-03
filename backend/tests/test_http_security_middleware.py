import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.http_middleware import CSRFMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware


def _make_csrf_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/v1/employer/opportunities")
    async def create_opportunity() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _make_headers_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _make_rate_limit_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/admin/overview")
    async def admin_overview() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/opportunities/feed")
    async def feed() -> dict[str, str]:
        return {"status": "ok"}

    return app


class TestCSRFMiddleware(unittest.TestCase):
    def test_blocks_cookie_authenticated_mutation_without_origin(self) -> None:
        app = _make_csrf_app()
        client = TestClient(app)
        with patch.object(settings, "CSRF_PROTECTION_ENABLED", True), patch.object(
            settings, "AUTH_SESSION_COOKIE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"), patch.object(
            settings, "CSRF_ENFORCE_ON_AUTH_COOKIE", True
        ):
            response = client.post(
                "/api/v1/employer/opportunities",
                cookies={"vidyaverse_session": "cookie-token"},
                json={"title": "x"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "csrf_origin_missing")

    def test_allows_cookie_authenticated_mutation_from_trusted_origin(self) -> None:
        app = _make_csrf_app()
        client = TestClient(app)
        with patch.object(settings, "CSRF_PROTECTION_ENABLED", True), patch.object(
            settings, "AUTH_SESSION_COOKIE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"), patch.object(
            settings, "CSRF_ENFORCE_ON_AUTH_COOKIE", True
        ), patch.object(
            settings, "CSRF_DOUBLE_SUBMIT_ENABLED", True
        ), patch.object(
            settings, "CSRF_COOKIE_NAME", "vidyaverse_csrf"
        ), patch.object(
            settings, "CSRF_HEADER_NAME", "X-CSRF-Token"
        ), patch.object(
            settings, "CSRF_TRUSTED_ORIGINS", ["https://web.test"]
        ):
            response = client.post(
                "/api/v1/employer/opportunities",
                cookies={"vidyaverse_session": "cookie-token", "vidyaverse_csrf": "csrf-token"},
                headers={"Origin": "https://web.test", "X-CSRF-Token": "csrf-token"},
                json={"title": "x"},
            )
        self.assertEqual(response.status_code, 200)

    def test_blocks_cookie_authenticated_mutation_without_csrf_token(self) -> None:
        app = _make_csrf_app()
        client = TestClient(app)
        with patch.object(settings, "CSRF_PROTECTION_ENABLED", True), patch.object(
            settings, "AUTH_SESSION_COOKIE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"), patch.object(
            settings, "CSRF_ENFORCE_ON_AUTH_COOKIE", True
        ), patch.object(
            settings, "CSRF_DOUBLE_SUBMIT_ENABLED", True
        ), patch.object(
            settings, "CSRF_COOKIE_NAME", "vidyaverse_csrf"
        ), patch.object(
            settings, "CSRF_TRUSTED_ORIGINS", ["https://web.test"]
        ):
            response = client.post(
                "/api/v1/employer/opportunities",
                cookies={"vidyaverse_session": "cookie-token"},
                headers={"Origin": "https://web.test"},
                json={"title": "x"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "csrf_token_missing")

    def test_blocks_cookie_authenticated_mutation_with_mismatched_csrf_token(self) -> None:
        app = _make_csrf_app()
        client = TestClient(app)
        with patch.object(settings, "CSRF_PROTECTION_ENABLED", True), patch.object(
            settings, "AUTH_SESSION_COOKIE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"), patch.object(
            settings, "CSRF_ENFORCE_ON_AUTH_COOKIE", True
        ), patch.object(
            settings, "CSRF_DOUBLE_SUBMIT_ENABLED", True
        ), patch.object(
            settings, "CSRF_COOKIE_NAME", "vidyaverse_csrf"
        ), patch.object(
            settings, "CSRF_HEADER_NAME", "X-CSRF-Token"
        ), patch.object(
            settings, "CSRF_TRUSTED_ORIGINS", ["https://web.test"]
        ):
            response = client.post(
                "/api/v1/employer/opportunities",
                cookies={"vidyaverse_session": "cookie-token", "vidyaverse_csrf": "csrf-cookie"},
                headers={"Origin": "https://web.test", "X-CSRF-Token": "csrf-header"},
                json={"title": "x"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("detail"), "csrf_token_mismatch")

    def test_allows_mutation_without_session_cookie(self) -> None:
        app = _make_csrf_app()
        client = TestClient(app)
        with patch.object(settings, "CSRF_PROTECTION_ENABLED", True), patch.object(
            settings, "AUTH_SESSION_COOKIE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"), patch.object(
            settings, "CSRF_ENFORCE_ON_AUTH_COOKIE", True
        ):
            response = client.post("/api/v1/employer/opportunities", json={"title": "x"})
        self.assertEqual(response.status_code, 200)


class TestSecurityHeadersMiddleware(unittest.TestCase):
    def test_applies_security_headers_with_csp_and_trusted_types(self) -> None:
        app = _make_headers_app()
        client = TestClient(app)
        with patch.object(settings, "SECURITY_HEADERS_ENABLED", True), patch.object(
            settings, "SECURITY_CSP_ENABLED", True
        ), patch.object(settings, "SECURITY_CSP_REPORT_ONLY", False):
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        csp = response.headers.get("content-security-policy") or ""
        self.assertIn("require-trusted-types-for 'script'", csp)
        self.assertIn("trusted-types default", csp)


class TestRateLimitMiddleware(unittest.TestCase):
    def test_uses_admin_specific_limit(self) -> None:
        app = _make_rate_limit_app()
        client = TestClient(app)
        checker = AsyncMock(return_value=None)

        with patch.object(settings, "RATE_LIMIT_ENABLED", True), patch.object(
            settings, "RATE_LIMIT_ADMIN_REQUESTS_PER_MINUTE", 20
        ), patch("app.core.http_middleware.check_rate_limit", new=checker):
            response = client.get("/api/v1/admin/overview")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(checker.await_args.kwargs["limit_per_minute"], 20)

    def test_uses_feed_specific_limit(self) -> None:
        app = _make_rate_limit_app()
        client = TestClient(app)
        checker = AsyncMock(return_value=None)

        with patch.object(settings, "RATE_LIMIT_ENABLED", True), patch.object(
            settings, "RATE_LIMIT_FEED_REQUESTS_PER_MINUTE", 100
        ), patch("app.core.http_middleware.check_rate_limit", new=checker):
            response = client.get("/api/v1/opportunities/feed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(checker.await_args.kwargs["limit_per_minute"], 100)


if __name__ == "__main__":
    unittest.main()
