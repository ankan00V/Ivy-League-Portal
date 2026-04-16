from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.core.config import settings
from app.core.redis import get_redis


def _stable_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def cache_key(*parts: str) -> str:
    normalized = ":".join(part.strip() for part in parts if part is not None)
    return f"vidyaverse:{_stable_hash(normalized)}"


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

