from __future__ import annotations

import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.metrics import REQUEST_LATENCY_SECONDS, REQUESTS_TOTAL, RESPONSES_TOTAL, init_metrics, metrics_available
from app.core.rate_limit import check_rate_limit


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None) if route is not None else None
    if isinstance(path, str) and path:
        return path
    return request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        if metrics_available():
            init_metrics()

        method = request.method.upper()
        route = _route_label(request)

        if REQUESTS_TOTAL is not None:
            REQUESTS_TOTAL.labels(method=method, route=route).inc()

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = max(0.0, time.perf_counter() - start)
            if REQUEST_LATENCY_SECONDS is not None:
                REQUEST_LATENCY_SECONDS.labels(method=method, route=route).observe(elapsed)
            if RESPONSES_TOTAL is not None:
                RESPONSES_TOTAL.labels(method=method, route=route, status="500").inc()
            raise

        elapsed = max(0.0, time.perf_counter() - start)
        if REQUEST_LATENCY_SECONDS is not None:
            REQUEST_LATENCY_SECONDS.labels(method=method, route=route).observe(elapsed)

        status = str(int(getattr(response, "status_code", 0) or 0))
        if RESPONSES_TOTAL is not None:
            RESPONSES_TOTAL.labels(method=method, route=route, status=status).inc()
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/metrics") or path.startswith("/health"):
            return await call_next(request)

        ip = _client_ip(request)
        action = _route_label(request)
        limit = int(settings.RATE_LIMIT_REQUESTS_PER_MINUTE)
        if path.startswith(f"{settings.API_V1_STR}/auth/"):
            limit = int(settings.RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE)

        decision = await check_rate_limit(subject=ip, action=action, limit_per_minute=limit)
        if decision is not None and not decision.allowed:
            headers = {
                "Retry-After": str(max(1, decision.retry_after_seconds)),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": str(decision.remaining),
            }
            return Response(status_code=429, content=b"Rate limit exceeded", headers=headers)

        response = await call_next(request)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response
