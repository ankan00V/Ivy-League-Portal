import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.deps import get_current_user
from app.core.security import create_access_token


def _request_with_cookie(cookie_name: str, token: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"cookie", f"{cookie_name}={token}".encode("utf-8"))],
    }
    return Request(scope)


class TestAuthCookieSession(unittest.IsolatedAsyncioTestCase):
    async def test_get_current_user_accepts_session_cookie(self) -> None:
        user_id = "64b64b64b64b64b64b64b64f"
        token = create_access_token(user_id, scopes=["user", "admin"])
        request = _request_with_cookie("vidyaverse_session", token)
        fake_user = SimpleNamespace(is_active=True)

        with patch("app.api.deps.User.get", new=AsyncMock(return_value=fake_user)):
            with patch("app.api.deps.settings.AUTH_SESSION_COOKIE_ENABLED", True):
                with patch("app.api.deps.settings.AUTH_SESSION_COOKIE_NAME", "vidyaverse_session"):
                    user = await get_current_user(request=request, token=None)

        self.assertIs(user, fake_user)
        self.assertIn("admin", getattr(user, "_token_scopes", []))

    async def test_get_current_user_prefers_cookie_when_bearer_is_malformed(self) -> None:
        user_id = "64b64b64b64b64b64b64b64f"
        token = create_access_token(user_id, scopes=["user"])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cookie", f"vidyaverse_session={token}".encode("utf-8"))],
        }
        request = Request(scope)
        fake_user = SimpleNamespace(is_active=True)

        with patch("app.api.deps.User.get", new=AsyncMock(return_value=fake_user)):
            user = await get_current_user(request=request, token="__cookie_session__")

        self.assertIs(user, fake_user)

    async def test_get_current_user_rejects_when_no_header_or_cookie(self) -> None:
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        with self.assertRaises(HTTPException) as ctx:
            await get_current_user(request=request, token=None)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_cookie_only_mode_rejects_valid_bearer_without_session_cookie(self) -> None:
        user_id = "64b64b64b64b64b64b64b64f"
        token = create_access_token(user_id, scopes=["user", "admin"])
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

        with patch("app.api.deps.auth_cookie_only_mode_enabled", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await get_current_user(request=request, token=token)

        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
