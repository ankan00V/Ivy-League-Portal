from __future__ import annotations

from typing import Optional

from app.core.config import settings

try:
    from redis.asyncio import Redis  # type: ignore
except Exception:  # pragma: no cover
    Redis = None  # type: ignore


_redis: Optional["Redis"] = None


def redis_available() -> bool:
    return Redis is not None and bool(settings.REDIS_URL)


def get_redis() -> Optional["Redis"]:
    global _redis
    if not redis_available():
        return None
    if _redis is not None:
        return _redis
    _redis = Redis.from_url(settings.REDIS_URL, encoding=None, decode_responses=False)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is None:
        return
    try:
        await _redis.close()
    finally:
        _redis = None

