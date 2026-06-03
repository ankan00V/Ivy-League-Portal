from __future__ import annotations

import json
import logging
import time
from uuid import uuid4
from urllib.parse import urlsplit
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.responses import Response

from app.core import metrics as metrics_module
from app.core.config import resolved_csp_value, settings
from app.core.rate_limit import check_rate_limit

logger = logging.getLogger("vidyaverse.http")


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
        if metrics_module.metrics_available():
            metrics_module.init_metrics()

        method = request.method.upper()
        route = _route_label(request)
        request_id_header = str(settings.REQUEST_ID_HEADER_NAME or "X-Request-ID").strip() or "X-Request-ID"
        request_id = (request.headers.get(request_id_header) or "").strip() or uuid4().hex
        request.state.request_id = request_id

        if metrics_module.REQUESTS_TOTAL is not None:
            metrics_module.REQUESTS_TOTAL.labels(method=method, route=route).inc()

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = max(0.0, time.perf_counter() - start)
            elapsed_ms = elapsed * 1000.0
            if metrics_module.REQUEST_LATENCY_SECONDS is not None:
                metrics_module.REQUEST_LATENCY_SECONDS.labels(method=method, route=route).observe(elapsed)
            if metrics_module.RESPONSES_TOTAL is not None:
                metrics_module.RESPONSES_TOTAL.labels(method=method, route=route, status="500").inc()
            self._log_request(
                request=request,
                request_id=request_id,
                route=route,
                status=500,
                elapsed_ms=elapsed_ms,
                level=logging.ERROR,
                error="unhandled_exception",
            )
            raise

        elapsed = max(0.0, time.perf_counter() - start)
        elapsed_ms = elapsed * 1000.0
        if metrics_module.REQUEST_LATENCY_SECONDS is not None:
            metrics_module.REQUEST_LATENCY_SECONDS.labels(method=method, route=route).observe(elapsed)

        status = str(int(getattr(response, "status_code", 0) or 0))
        if metrics_module.RESPONSES_TOTAL is not None:
            metrics_module.RESPONSES_TOTAL.labels(method=method, route=route, status=status).inc()
        response.headers.setdefault(request_id_header, request_id)

        slow_threshold_ms = max(0.0, float(settings.OBSERVABILITY_SLOW_REQUEST_MS))
        is_slow = slow_threshold_ms > 0.0 and elapsed_ms >= slow_threshold_ms
        if is_slow and metrics_module.SLOW_REQUESTS_TOTAL is not None:
            metrics_module.SLOW_REQUESTS_TOTAL.labels(method=method, route=route).inc()

        self._log_request(
            request=request,
            request_id=request_id,
            route=route,
            status=int(status),
            elapsed_ms=elapsed_ms,
            level=logging.WARNING if is_slow else logging.INFO,
            slow=is_slow,
        )
        return response

    def _log_request(
        self,
        *,
        request: Request,
        request_id: str,
        route: str,
        status: int,
        elapsed_ms: float,
        level: int,
        slow: bool = False,
        error: str | None = None,
    ) -> None:
        payload = {
            "event": "http_request_completed",
            "request_id": request_id,
            "method": request.method.upper(),
            "path": request.url.path,
            "route": route,
            "status": int(status),
            "elapsed_ms": round(float(elapsed_ms), 3),
            "client_ip": _client_ip(request),
            "slow": bool(slow),
        }
        if error:
            payload["error"] = error
        logger.log(level, json.dumps(payload, sort_keys=True))


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
        elif path.startswith(f"{settings.API_V1_STR}/admin/"):
            limit = int(settings.RATE_LIMIT_ADMIN_REQUESTS_PER_MINUTE)
        elif path.startswith(f"{settings.API_V1_STR}/opportunities/feed"):
            limit = int(settings.RATE_LIMIT_FEED_REQUESTS_PER_MINUTE)

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

        if settings.CSRF_DOUBLE_SUBMIT_ENABLED:
            csrf_cookie_name = str(settings.CSRF_COOKIE_NAME or "").strip()
            csrf_header_name = str(settings.CSRF_HEADER_NAME or "X-CSRF-Token").strip() or "X-CSRF-Token"
            csrf_cookie = str(request.cookies.get(csrf_cookie_name) or "").strip() if csrf_cookie_name else ""
            csrf_header = str(request.headers.get(csrf_header_name) or "").strip()
            if not csrf_cookie or not csrf_header:
                return JSONResponse(status_code=403, content={"detail": "csrf_token_missing"})
            if csrf_cookie != csrf_header:
                return JSONResponse(status_code=403, content={"detail": "csrf_token_mismatch"})

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
            csp_value = resolved_csp_value()
            report_uri = str(settings.SECURITY_CSP_REPORT_URI or "").strip()
            if report_uri and "report-uri" not in csp_value:
                csp_value = f"{csp_value.rstrip('; ')}; report-uri {report_uri}; report-to csp-endpoint"
            csp_key = (
                "Content-Security-Policy-Report-Only"
                if settings.SECURITY_CSP_REPORT_ONLY
                else "Content-Security-Policy"
            )
            response.headers.setdefault(csp_key, csp_value)
            if report_uri:
                response.headers.setdefault(
                    "Report-To",
                    '{"group":"csp-endpoint","max_age":10886400,"endpoints":[{"url":"' + report_uri + '"}]}',
                )

        if settings.ENVIRONMENT.strip().lower() == "production" or settings.AUTH_SESSION_COOKIE_SECURE:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        return response
