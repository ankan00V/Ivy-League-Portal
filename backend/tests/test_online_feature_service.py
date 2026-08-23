import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.online_feature_service import online_feature_service


class _FakePipeline:
    def __init__(self) -> None:
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def set(self, key, value, ex):
        self.commands.append(("set", key, value, ex))

    def hset(self, key, field, value):
        self.commands.append(("hset", key, field, value))

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))

    async def execute(self):
        return True


class _FakeRedis:
    def __init__(self) -> None:
        self.pipeline_obj = _FakePipeline()

    def pipeline(self, transaction=False):
        return self.pipeline_obj


class TestOnlineFeatureService(unittest.IsolatedAsyncioTestCase):
    async def test_publish_rows_writes_redis_payloads(self) -> None:
        fake_redis = _FakeRedis()
        row = SimpleNamespace(
            row_key="row-1",
            date="2026-01-01",
            user_id="user-1",
            opportunity_id="opp-1",
            ranking_mode="ml",
            experiment_key="exp",
            experiment_variant="a",
            traffic_type="real",
            rank_position=1,
            match_score=88.0,
            features={"semantic": 0.8},
            labels={"applied": 1},
            source_event_id="event-1",
            updated_at=None,
        )
        with patch("app.services.online_feature_service.get_feature_store_redis", return_value=fake_redis):
            published = await online_feature_service.publish_rows([row])

        self.assertEqual(published, 1)
        set_commands = [cmd for cmd in fake_redis.pipeline_obj.commands if cmd[0] == "set"]
        self.assertEqual(len(set_commands), 1)
        payload = json.loads(set_commands[0][2].decode("utf-8"))
        self.assertEqual(payload["row_key"], "row-1")
        self.assertEqual(payload["opportunity_id"], "opp-1")


    async def test_expire_is_issued_once_per_user_not_once_per_row(self) -> None:
        """EXPIRE targets the per-user index, so per-row calls are pure waste.

        This is a cost test, not a correctness one. The real rebuild publishes
        ~37,000 rows across 5 users; issuing EXPIRE inside the row loop sent
        ~37,000 identical commands and burned a third of a 500,000-request
        monthly quota on every rebuild. Per-user is equivalent and ~33% cheaper.
        """
        fake_redis = _FakeRedis()

        def _row(user_id: str, opportunity_id: str):
            return SimpleNamespace(
                row_key=f"{user_id}-{opportunity_id}",
                date="2026-01-01",
                user_id=user_id,
                opportunity_id=opportunity_id,
                ranking_mode="ml",
                experiment_key="exp",
                experiment_variant="a",
                traffic_type="real",
                rank_position=1,
                match_score=88.0,
                features={"semantic": 0.8},
                labels={"applied": 1},
                source_event_id="event-1",
                updated_at=None,
            )

        # 6 rows, 2 users.
        rows = [_row("user-1", f"opp-{i}") for i in range(4)] + [
            _row("user-2", f"opp-{i}") for i in range(2)
        ]
        with patch("app.services.online_feature_service.get_feature_store_redis", return_value=fake_redis):
            published = await online_feature_service.publish_rows(rows)

        commands = fake_redis.pipeline_obj.commands
        self.assertEqual(published, 6)
        self.assertEqual(len([c for c in commands if c[0] == "set"]), 6)
        self.assertEqual(len([c for c in commands if c[0] == "hset"]), 6)

        expires = [c for c in commands if c[0] == "expire"]
        self.assertEqual(len(expires), 2, "one EXPIRE per user, not per row")
        self.assertEqual(len({c[1] for c in expires}), 2)

        # Each user's index must still be given a TTL, and only after its fields
        # are written - an EXPIRE that landed before the HSETs would be correct
        # here but fragile, so assert the ordering too.
        for key in {c[1] for c in expires}:
            last_hset = max(i for i, c in enumerate(commands) if c[0] == "hset" and c[1] == key)
            expire_at = next(i for i, c in enumerate(commands) if c[0] == "expire" and c[1] == key)
            self.assertGreater(expire_at, last_hset)

    async def test_falls_back_to_shared_redis_without_dedicated_url(self) -> None:
        # The dedicated feature-store instance is optional; an unset URL must
        # keep working against the shared client rather than silently no-op.
        from app.core import redis as redis_mod

        sentinel = object()
        with (
            patch.object(redis_mod.settings, "REDIS_FEATURE_STORE_URL", None),
            patch.object(redis_mod, "get_redis", return_value=sentinel),
        ):
            self.assertIs(redis_mod.get_feature_store_redis(), sentinel)


    async def test_dedicated_getters_execute_for_real(self) -> None:
        """Call the getters instead of patching them.

        Every other test patches get_feature_store_redis/get_cache_redis, so a
        NameError inside those functions stayed invisible through a full green
        suite and only surfaced against a live instance. This exercises the real
        bodies with a stubbed client factory.
        """
        from app.core import redis as redis_mod

        sentinel = object()
        for attr, getter in (
            ("REDIS_FEATURE_STORE_URL", redis_mod.get_feature_store_redis),
            ("REDIS_CACHE_URL", redis_mod.get_cache_redis),
        ):
            with self.subTest(setting=attr):
                redis_mod._feature_redis = None
                redis_mod._cache_redis = None
                with (
                    patch.object(redis_mod.settings, attr, "rediss://user:pw@example.upstash.io:6379"),
                    patch.object(redis_mod.Redis, "from_url", return_value=sentinel),
                ):
                    self.assertIs(getter(), sentinel)
        redis_mod._feature_redis = None
        redis_mod._cache_redis = None


if __name__ == "__main__":
    unittest.main()
