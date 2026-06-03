from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings
from app.core.redis import get_redis


def _stable_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def cache_key(*parts: str) -> str:
    normalized = ":".join(part.strip() for part in parts if part is not None)
    return f"vidyaverse:{_stable_hash(normalized)}"


@dataclass(frozen=True)
class CacheStats:
    namespace: str
    hits: int
    misses: int
    hit_rate: float
    key_count: int


class CacheManager:
    def __init__(self, *, prefix: str = "vidyaverse") -> None:
        self.prefix = prefix.strip(":") or "vidyaverse"

    def key(self, namespace: str, key: str) -> str:
        namespace_value = str(namespace or "default").strip(":")
        key_value = str(key or "default").strip(":")
        return f"{self.prefix}:{namespace_value}:{key_value}"

    def hashed_key(self, namespace: str, *parts: str) -> str:
        normalized = ":".join(str(part).strip() for part in parts if part is not None)
        return self.key(namespace, _stable_hash(normalized))

    async def get_json(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        full_key = self.key(namespace, key)
        raw = await cache_get_bytes(full_key)
        if not raw:
            await self._increment_stat(namespace, "misses")
            return None
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            await self._increment_stat(namespace, "misses")
            return None
        await self._increment_stat(namespace, "hits")
        return value if isinstance(value, dict) else {"value": value}

    async def set_json(self, namespace: str, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        if int(ttl_seconds) <= 0:
            raise ValueError("ttl_seconds must be positive")
        await cache_set_json(self.key(namespace, key), value, ttl_seconds=int(ttl_seconds))

    async def delete(self, namespace: str, key: str) -> int:
        redis = get_redis()
        if redis is None:
            return 0
        try:
            return int(await redis.delete(self.key(namespace, key)))
        except Exception:
            return 0

    async def delete_pattern(self, namespace: str, pattern: str = "*") -> int:
        redis = get_redis()
        if redis is None:
            return 0
        match = self.key(namespace, pattern)
        deleted = 0
        try:
            async for key in redis.scan_iter(match=match, count=200):
                deleted += int(await redis.delete(key))
        except AttributeError:
            try:
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor=cursor, match=match, count=200)
                    if keys:
                        deleted += int(await redis.delete(*keys))
                    if int(cursor) == 0:
                        break
            except Exception:
                return deleted
        except Exception:
            return deleted
        return deleted

    async def stats(self, namespace: str) -> CacheStats:
        redis = get_redis()
        hits = await self._read_stat(namespace, "hits")
        misses = await self._read_stat(namespace, "misses")
        total = hits + misses
        key_count = 0
        if redis is not None:
            try:
                async for _key in redis.scan_iter(match=self.key(namespace, "*"), count=500):
                    key_count += 1
            except Exception:
                key_count = 0
        return CacheStats(
            namespace=namespace,
            hits=hits,
            misses=misses,
            hit_rate=round(float(hits / total), 4) if total else 0.0,
            key_count=key_count,
        )

    async def publish_model_update(self, model_version: str) -> int:
        redis = get_redis()
        if redis is None:
            return 0
        payload = json.dumps({"event": "model_update", "model_version": str(model_version)}, separators=(",", ":"))
        try:
            return int(await redis.publish("channel:model_update", payload))
        except Exception:
            return 0

    async def invalidate_after_opportunity_change(self, *, opportunity_id: str | None = None) -> dict[str, int]:
        deleted = {
            "opps_feed": await self.delete_pattern("opps:feed", "*"),
            "opps_search": await self.delete_pattern("opps:search", "*"),
        }
        if opportunity_id:
            deleted["opps_detail"] = await self.delete("opps:detail", str(opportunity_id))
        return deleted

    async def invalidate_after_user_interaction(self, *, user_id: str) -> dict[str, int]:
        return {
            "user_embedding": await self.delete("user:embedding", str(user_id)),
            "feed_candidates": await self.delete_pattern("opps:feed:candidates", f"{user_id}:*"),
        }

    async def invalidate_after_profile_update(self, *, user_id: str) -> dict[str, int]:
        return {
            "user_profile": await self.delete("user:profile", str(user_id)),
            "user_embedding": await self.delete("user:embedding", str(user_id)),
            "feed_candidates": await self.delete_pattern("opps:feed:candidates", f"{user_id}:*"),
        }

    async def _increment_stat(self, namespace: str, metric: str) -> None:
        redis = get_redis()
        if redis is None:
            return
        try:
            await redis.incr(self.key("cache:stats", f"{namespace}:{metric}"))
        except Exception:
            return

    async def _read_stat(self, namespace: str, metric: str) -> int:
        redis = get_redis()
        if redis is None:
            return 0
        try:
            value = await redis.get(self.key("cache:stats", f"{namespace}:{metric}"))
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8")
            return int(value or 0)
        except Exception:
            return 0


async def cache_get_bytes(key: str) -> Optional[bytes]:
    if not settings.CACHE_ENABLED:
        return None
    redis = get_redis()
    if redis is None:
        return None
    try:
        value = await redis.get(key)
        return value if isinstance(value, (bytes, bytearray)) else None
    except Exception:
        return None


async def cache_set_bytes(key: str, value: bytes, ttl_seconds: int) -> None:
    if not settings.CACHE_ENABLED:
        return
    redis = get_redis()
    if redis is None:
        return
    try:
        await redis.set(key, value, ex=max(1, int(ttl_seconds)))
    except Exception:
        return


async def cache_get_json(key: str) -> Optional[dict[str, Any]]:
    raw = await cache_get_bytes(key)
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


async def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:
        return
    await cache_set_bytes(key, raw, ttl_seconds=ttl_seconds)


cache_manager = CacheManager()
