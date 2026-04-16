from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Optional

from app.core.config import settings
from app.core.redis import get_redis


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: int


def _bucket_key(*parts: str) -> str:
    return "rl:" + ":".join(part.strip() for part in parts if part)


async def check_rate_limit(
    *,
    subject: str,
    action: str,
    limit_per_minute: int,
) -> Optional[RateLimitDecision]:
    if not settings.RATE_LIMIT_ENABLED:
        return None
    limit = max(1, int(limit_per_minute))
    now = int(time())
    window = now // 60
    key = _bucket_key(subject, action, str(window))
    redis = get_redis()
    if redis is None:
        return None
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 70)
        remaining = max(0, limit - int(current))
        allowed = int(current) <= limit
        retry_after = 60 - (now % 60) if not allowed else 0
        return RateLimitDecision(
            allowed=allowed,
            remaining=remaining,
            limit=limit,
            retry_after_seconds=int(retry_after),
        )
    except Exception:
        return None

