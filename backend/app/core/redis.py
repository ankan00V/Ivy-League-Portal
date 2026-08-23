from __future__ import annotations

from typing import Optional

from app.core.config import settings

try:
    from redis.asyncio import Redis  # type: ignore
except Exception:  # pragma: no cover
    Redis = None  # type: ignore


_redis: Optional["Redis"] = None
_feature_redis: Optional["Redis"] = None
_cache_redis: Optional["Redis"] = None


def redis_available() -> bool:
    return Redis is not None and bool(settings.REDIS_URL)


def get_redis() -> Optional["Redis"]:
    global _redis
    if not redis_available():
        return None
    if _redis is not None:
        return _redis
    _redis = Redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=False)
    return _redis


def get_feature_store_redis() -> Optional["Redis"]:
    """Connection for the online feature store.

    Separate from get_redis() so the store's write volume can be pointed at its
    own instance. Auth sessions and revocation keys must stay put: moving them
    logs everyone out, and a session revoked on the old instance would come back
    to life on the new one. Feature rows carry neither risk - they are TTL'd and
    rebuilt from Postgres - so this is the half that is safe to relocate.

    Falls back to the shared client when no dedicated URL is set.
    """
    global _feature_redis
    configured = str(settings.REDIS_FEATURE_STORE_URL or "").strip()
    if not configured:
        return get_redis()
    if _feature_redis is not None:
        return _feature_redis
    _feature_redis = Redis.from_url(configured, encoding="utf-8", decode_responses=False)
    return _feature_redis


def get_cache_redis() -> Optional["Redis"]:
    """Connection for the response cache and rate-limit counters.

    Disposable like the feature store: a cold cache re-fetches, and a reset
    rate-limit window costs at most one extra allowed request. Keeping it off the
    auth instance means cache churn cannot exhaust the quota that sessions and
    revocation keys depend on. Falls back to the shared client.
    """
    global _cache_redis
    configured = str(settings.REDIS_CACHE_URL or "").strip()
    if not configured:
        return get_redis()
    if _cache_redis is not None:
        return _cache_redis
    _cache_redis = Redis.from_url(configured, encoding="utf-8", decode_responses=False)
    return _cache_redis


async def close_redis() -> None:
    global _redis, _feature_redis, _cache_redis
    for name in ("_redis", "_feature_redis", "_cache_redis"):
        client = globals().get(name)
        if client is None:
            continue
        try:
            await client.close()
        finally:
            globals()[name] = None
