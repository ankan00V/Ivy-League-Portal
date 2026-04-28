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
        with patch("app.services.online_feature_service.get_redis", return_value=fake_redis):
            published = await online_feature_service.publish_rows([row])

        self.assertEqual(published, 1)
        set_commands = [cmd for cmd in fake_redis.pipeline_obj.commands if cmd[0] == "set"]
        self.assertEqual(len(set_commands), 1)
        payload = json.loads(set_commands[0][2].decode("utf-8"))
        self.assertEqual(payload["row_key"], "row-1")
        self.assertEqual(payload["opportunity_id"], "opp-1")


if __name__ == "__main__":
    unittest.main()
