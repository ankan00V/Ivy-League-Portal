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



async def _check_daily(subject: str, action: str, limit_per_day: int, *, fail_closed: bool) -> Optional[RateLimitDecision]:
    """Same fixed-window scheme, bucketed by day instead of minute."""
    if not settings.RATE_LIMIT_ENABLED:
        return None
    limit = max(1, int(limit_per_day))
    now = int(time())
    day = now // 86_400
    key = _bucket_key(subject, f"{action}:day", str(day))
    redis = get_cache_redis()
    if redis is None:
        return _unavailable(action, "redis_unconfigured", fail_closed=fail_closed, limit=limit)
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 86_460)
        allowed = int(current) <= limit
        return RateLimitDecision(
            allowed=allowed,
            remaining=max(0, limit - int(current)),
            limit=limit,
            retry_after_seconds=0 if allowed else 86_400 - (now % 86_400),
        )
    except Exception as exc:
        return _unavailable(action, f"{type(exc).__name__}", fail_closed=fail_closed, limit=limit)


async def enforce_ai_budget(*, user_id: str, action: str) -> None:
    """Meter a paid endpoint against the account that is spending.

    Ask AI, the assistant and the resume review each run retrieval, a
    cross-encoder and an LLM generation, so every call costs real money. The
    HTTP middleware does not cover that: it is keyed by IP at a default of
    240/min, which is roughly 14,000 model calls an hour from one address, and
    IP is the wrong key in both directions here - a college behind a single NAT
    shares one bucket, while anyone with rotating addresses has none.

    Fails closed. If Redis is unreachable the budget cannot be counted, and an
    uncounted paid endpoint is a worse outcome than a brief refusal; this is the
    same reasoning the credential endpoints already use.

    Raises HTTPException(429) with Retry-After when either window is exhausted.
    """
    from fastapi import HTTPException  # local import: keeps this module web-framework free elsewhere

    for decision, scope in (
        (
            await check_rate_limit(
                subject=user_id,
                action=action,
                limit_per_minute=int(settings.RATE_LIMIT_AI_REQUESTS_PER_MINUTE),
                fail_closed=True,
            ),
            "minute",
        ),
        (
            await _check_daily(
                user_id,
                action,
                int(settings.RATE_LIMIT_AI_REQUESTS_PER_DAY),
                fail_closed=True,
            ),
            "day",
        ),
    ):
        if decision is not None and not decision.allowed:
            logger.info("AI budget exhausted for %s on %s (%s window)", action, user_id, scope)
            raise HTTPException(
                status_code=429,
                detail=f"AI request limit reached for this account ({decision.limit} per {scope}). Try again later.",
                headers={"Retry-After": str(max(1, int(decision.retry_after_seconds)))},
            )
