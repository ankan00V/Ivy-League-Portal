import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import session_security_service as module
from app.services.session_security_service import session_security_service as service


class _FakeRedis:
    """Minimal in-memory stand-in for the operations the service uses."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    async def delete(self, key: str):
        self.store.pop(key, None)

    async def srem(self, key: str, member: str):
        self.sets.get(key, set()).discard(member)

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    async def expire(self, key: str, ttl: int):
        self.ttls[key] = ttl


class TestSessionRevocation(unittest.IsolatedAsyncioTestCase):
    """Logging out has to actually log you out.

    With AUTH_SESSION_REQUIRE_SERVER_STATE false - the shipped configuration -
    validate_session treated a missing session record as `session_not_found` ->
    allowed. Deleting the record on logout therefore revoked nothing: a stolen
    token kept working after logout, after "sign out all devices" and after an
    admin revoked the session, until the JWT expired on its own.
    """

    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.user = SimpleNamespace(id="6a6a141b445a4c527370e5e1")
        self.session_id = "sess-test-1"
        self.redis.store[service._session_key(self.session_id)] = json.dumps(
            {"user_id": str(self.user.id), "fingerprint": ""}
        ).encode()

    async def _validate(self):
        return await service.validate_session(
            user=self.user, session_id=self.session_id, request=None
        )

    async def test_logout_revokes_even_in_permissive_mode(self) -> None:
        with (
            patch.object(module, "get_redis", return_value=self.redis),
            patch.object(module.settings, "AUTH_SESSION_STORE_ENABLED", True),
            patch.object(module.settings, "AUTH_SESSION_REQUIRE_SERVER_STATE", False),
            patch.object(module.settings, "AUTH_SESSION_BIND_DEVICE", False),
        ):
            before = await self._validate()
            self.assertTrue(before.allowed)

            await service.invalidate_session(self.session_id)

            after = await self._validate()
            self.assertFalse(after.allowed)
            self.assertEqual(after.reason, "session_revoked")

    async def test_revocation_tombstone_outlives_the_access_token(self) -> None:
        """A tombstone shorter than the token would let it come back to life."""
        with (
            patch.object(module, "get_redis", return_value=self.redis),
            patch.object(module.settings, "AUTH_SESSION_STORE_ENABLED", True),
            patch.object(module.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60),
        ):
            await service.invalidate_session(self.session_id)
            ttl = self.redis.ttls[service._revoked_key(self.session_id)]
        self.assertGreater(ttl, 60 * 60)

    async def test_sign_out_all_devices_revokes_each_session(self) -> None:
        other = "sess-test-2"
        user_key = service._user_sessions_key(str(self.user.id))
        self.redis.sets[user_key] = {self.session_id, other}
        with (
            patch.object(module, "get_redis", return_value=self.redis),
            patch.object(module.settings, "AUTH_SESSION_STORE_ENABLED", True),
        ):
            revoked = await service.invalidate_user_sessions(str(self.user.id))
        self.assertEqual(revoked, 2)
        for sid in (self.session_id, other):
            self.assertIn(service._revoked_key(sid), self.redis.store)

    async def test_a_live_session_is_untouched(self) -> None:
        with (
            patch.object(module, "get_redis", return_value=self.redis),
            patch.object(module.settings, "AUTH_SESSION_STORE_ENABLED", True),
            patch.object(module.settings, "AUTH_SESSION_REQUIRE_SERVER_STATE", False),
            patch.object(module.settings, "AUTH_SESSION_BIND_DEVICE", False),
        ):
            result = await self._validate()
        self.assertTrue(result.allowed)


if __name__ == "__main__":
    unittest.main()
