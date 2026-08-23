from __future__ import annotations

import logging
from dataclasses import dataclass
from time import time
from typing import Optional

from app.core.config import settings
from app.core.redis import get_cache_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: int


def _bucket_key(*parts: str) -> str:
    return "rl:" + ":".join(part.strip() for part in parts if part)


def _unavailable(action: str, reason: str, *, fail_closed: bool, limit: int) -> Optional[RateLimitDecision]:
    """Handle Redis being unavailable.

    This previously returned None - i.e. "allowed" - with no log and no metric,
    so a Redis blip silently removed every limit in the application, including
    the auth limiter, and looked identical to a healthy request.
    """
    logger.error(
        "rate limit backend unavailable action=%s reason=%s fail_closed=%s",
        action,
        reason,
        fail_closed,
    )
    if not fail_closed:
        return None
    return RateLimitDecision(allowed=False, remaining=0, limit=limit, retry_after_seconds=5)


async def check_rate_limit(
    *,
    subject: str,
    action: str,
    limit_per_minute: int,
    fail_closed: bool = False,
) -> Optional[RateLimitDecision]:
    """Fixed-window limiter.

    `fail_closed` decides what happens when the backing store is unreachable.
    Callers guarding credential endpoints should set it: losing Redis should not
    silently disable brute-force protection.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return None
    limit = max(1, int(limit_per_minute))
    now = int(time())
    window = now // 60
    key = _bucket_key(subject, action, str(window))
    redis = get_cache_redis()
    if redis is None:
        return _unavailable(action, "redis_unconfigured", fail_closed=fail_closed, limit=limit)
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
    except Exception as exc:
        return _unavailable(
            action, f"{type(exc).__name__}", fail_closed=fail_closed, limit=limit
        )

