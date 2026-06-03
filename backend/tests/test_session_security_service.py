import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services.session_security_service import session_security_service


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    async def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def srem(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).discard(value)


def _request(*, ip: str = "203.0.113.10", user_agent: str = "test-agent") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users/me",
            "headers": [(b"user-agent", user_agent.encode("utf-8")), (b"accept-language", b"en-US")],
            "client": (ip, 12345),
        }
    )


class TestSessionSecurityService(unittest.IsolatedAsyncioTestCase):
    async def test_validates_created_session_with_matching_fingerprint(self) -> None:
        redis = FakeRedis()
        user = SimpleNamespace(id="user-1", email="user@example.com", account_type="candidate")
        session_id = "session-1"

        with patch("app.services.session_security_service.get_redis", return_value=redis), patch.object(
            settings, "AUTH_SESSION_STORE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_REQUIRE_SERVER_STATE", True), patch.object(
            settings, "AUTH_SESSION_BIND_DEVICE", True
        ), patch.object(settings, "AUTH_SESSION_REDIS_PREFIX", "test:auth"):
            await session_security_service.create_session(
                user=user,
                session_id=session_id,
                request=_request(),
                ttl_seconds=300,
                scopes=["user"],
            )
            result = await session_security_service.validate_session(
                user=user,
                session_id=session_id,
                request=_request(),
            )

        self.assertTrue(result.allowed)

    async def test_rejects_device_fingerprint_mismatch_when_binding_enabled(self) -> None:
        redis = FakeRedis()
        user = SimpleNamespace(id="user-1", email="user@example.com", account_type="candidate")
        session_id = "session-1"

        with patch("app.services.session_security_service.get_redis", return_value=redis), patch.object(
            settings, "AUTH_SESSION_STORE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_REQUIRE_SERVER_STATE", True), patch.object(
            settings, "AUTH_SESSION_BIND_DEVICE", True
        ), patch.object(settings, "AUTH_SESSION_REDIS_PREFIX", "test:auth"), patch(
            "app.services.session_security_service.auth_security_service.audit_event", new=AsyncMock()
        ):
            await session_security_service.create_session(
                user=user,
                session_id=session_id,
                request=_request(user_agent="first-agent"),
                ttl_seconds=300,
                scopes=["user"],
            )
            result = await session_security_service.validate_session(
                user=user,
                session_id=session_id,
                request=_request(user_agent="second-agent"),
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "device_fingerprint_mismatch")

    async def test_rejects_missing_server_session_when_required(self) -> None:
        redis = FakeRedis()
        user = SimpleNamespace(id="user-1", email="user@example.com", account_type="candidate")

        with patch("app.services.session_security_service.get_redis", return_value=redis), patch.object(
            settings, "AUTH_SESSION_STORE_ENABLED", True
        ), patch.object(settings, "AUTH_SESSION_REQUIRE_SERVER_STATE", True), patch.object(
            settings, "AUTH_SESSION_REDIS_PREFIX", "test:auth"
        ):
            result = await session_security_service.validate_session(
                user=user,
                session_id="missing-session",
                request=_request(),
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "session_not_found")


if __name__ == "__main__":
    unittest.main()
