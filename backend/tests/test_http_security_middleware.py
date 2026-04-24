import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.http_middleware import CSRFMiddleware, SecurityHeadersMiddleware


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
            settings, "CSRF_TRUSTED_ORIGINS", ["https://web.test"]
        ):
            response = client.post(
                "/api/v1/employer/opportunities",
                cookies={"vidyaverse_session": "cookie-token"},
                headers={"Origin": "https://web.test"},
                json={"title": "x"},
            )
        self.assertEqual(response.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
