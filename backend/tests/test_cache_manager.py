import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.cache import CacheManager


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: bytes, ex: int) -> None:
        self.values[key] = value
        self.values[f"{key}:ttl"] = str(ex).encode("utf-8")

    async def incr(self, key: str) -> int:
        current = int((self.values.get(key) or b"0").decode("utf-8")) + 1
        self.values[key] = str(current).encode("utf-8")
        return current

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            self.deleted.append(str(key))
            if key in self.values:
                count += 1
                self.values.pop(key, None)
        return count

    async def scan_iter(self, match: str, count: int = 200):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


class TestCacheManager(unittest.IsolatedAsyncioTestCase):
    async def test_json_cache_records_hit_and_miss_stats(self) -> None:
        redis = FakeRedis()
        manager = CacheManager(prefix="test")

        with patch("app.core.cache.get_redis", return_value=redis):
            self.assertIsNone(await manager.get_json("user:profile", "u1"))
            await manager.set_json("user:profile", "u1", {"name": "A"}, ttl_seconds=60)
            self.assertEqual(await manager.get_json("user:profile", "u1"), {"name": "A"})
            stats = await manager.stats("user:profile")

        self.assertEqual(stats.hits, 1)
        self.assertEqual(stats.misses, 1)
        self.assertEqual(stats.hit_rate, 0.5)

    async def test_delete_pattern_and_model_update_pubsub(self) -> None:
        redis = FakeRedis()
        manager = CacheManager(prefix="test")

        with patch("app.core.cache.get_redis", return_value=redis):
            await manager.set_json("opps:feed:candidates", "u1:a", {"ids": []}, ttl_seconds=60)
            await manager.set_json("opps:feed:candidates", "u1:b", {"ids": []}, ttl_seconds=60)
            deleted = await manager.delete_pattern("opps:feed:candidates", "u1:*")
            subscribers = await manager.publish_model_update("ranker-v2")

        self.assertGreaterEqual(deleted, 2)
        self.assertEqual(subscribers, 1)
        self.assertEqual(redis.published[0][0], "channel:model_update")


if __name__ == "__main__":
    unittest.main()
