from __future__ import annotations

import time
from urllib.parse import urlsplit
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.responses import Response

from app.core.config import resolved_csp_value, settings
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


def _origin_from_value(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    split = urlsplit(candidate)
    if split.scheme not in {"http", "https"} or not split.netloc:
        return None
    return f"{split.scheme}://{split.netloc}"


def _trusted_csrf_origins() -> set[str]:
    explicit_origins = {
        origin
        for origin in (_origin_from_value(item) for item in list(settings.CSRF_TRUSTED_ORIGINS or []))
        if origin
    }
    if explicit_origins:
        trusted = set(explicit_origins)
    else:
        trusted = {
            origin
            for origin in (_origin_from_value(item) for item in list(settings.BACKEND_CORS_ORIGINS or []))
            if origin
        }

    for extra in (settings.FRONTEND_OAUTH_SUCCESS_URL, settings.FRONTEND_OAUTH_FAILURE_URL):
        origin = _origin_from_value(extra)
        if origin:
            trusted.add(origin)
    return trusted


def _request_origin(request: Request) -> str | None:
    origin = _origin_from_value(request.headers.get("origin"))
    if origin:
        return origin
    return _origin_from_value(request.headers.get("referer"))


def _response_with_vary_origin(response: Response) -> Response:
    existing = response.headers.get("vary")
    if not existing:
        response.headers["Vary"] = "Origin"
        return response
    normalized = [item.strip().lower() for item in existing.split(",") if item.strip()]
    if "origin" not in normalized:
        response.headers["Vary"] = f"{existing}, Origin"
    return response


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


class CSRFMiddleware(BaseHTTPMiddleware):
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        if not settings.CSRF_PROTECTION_ENABLED:
            return await call_next(request)

        if request.method.upper() in self._SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/metrics") or path.startswith("/health"):
            return await call_next(request)

        if not settings.AUTH_SESSION_COOKIE_ENABLED or not settings.CSRF_ENFORCE_ON_AUTH_COOKIE:
            return await call_next(request)

        cookie_name = (settings.AUTH_SESSION_COOKIE_NAME or "").strip()
        if not cookie_name:
            return await call_next(request)
        session_cookie_value = (request.cookies.get(cookie_name) or "").strip()
        if not session_cookie_value:
            return await call_next(request)

        origin = _request_origin(request)
        if not origin:
            return JSONResponse(status_code=403, content={"detail": "csrf_origin_missing"})

        trusted_origins = _trusted_csrf_origins()
        same_origin = origin == f"{request.url.scheme}://{request.url.netloc}"
        if not same_origin and origin not in trusted_origins:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "csrf_origin_mismatch",
                    "origin": origin,
                },
            )

        response = await call_next(request)
        return _response_with_vary_origin(response)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        response = await call_next(request)
        if not settings.SECURITY_HEADERS_ENABLED:
            return response

        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault("X-DNS-Prefetch-Control", "off")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        if settings.SECURITY_CSP_ENABLED and request.url.path not in {
            "/docs",
            "/redoc",
            f"{settings.API_V1_STR}/openapi.json",
        }:
            csp_key = (
                "Content-Security-Policy-Report-Only"
                if settings.SECURITY_CSP_REPORT_ONLY
                else "Content-Security-Policy"
            )
            response.headers.setdefault(csp_key, resolved_csp_value())

        if settings.ENVIRONMENT.strip().lower() == "production" or settings.AUTH_SESSION_COOKIE_SECURE:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        return response
