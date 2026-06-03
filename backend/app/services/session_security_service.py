from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from jose import JWTError, jwt

from app.core.config import settings
from app.core.redis import get_redis
from app.core.time import utc_now
from app.models.user import User
from app.services.auth_security_service import auth_security_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionValidationResult:
    allowed: bool
    reason: str = "ok"


class SessionSecurityService:
    def new_session_id(self) -> str:
        return uuid4().hex

    def extract_session_id(self, token: str | None) -> str | None:
        candidate = str(token or "").strip()
        if not candidate:
            return None
        try:
            payload = jwt.decode(candidate, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError:
            return None
        return str(payload.get("jti") or "").strip() or None

    def fingerprint_request(self, request: Request | None) -> str:
        headers = getattr(request, "headers", {}) if request is not None else {}
        user_agent = str(headers.get("user-agent", "") or "").strip().lower()
        accept_language = str(headers.get("accept-language", "") or "").strip().lower()
        ip_prefix = self._ip_prefix(self._client_ip(request))
        raw = "|".join([user_agent, accept_language, ip_prefix])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def create_session(
        self,
        *,
        user: User,
        session_id: str,
        request: Request | None,
        ttl_seconds: int,
        scopes: list[str],
        session_type: str = "user",
    ) -> None:
        if not settings.AUTH_SESSION_STORE_ENABLED:
            return
        redis = get_redis()
        if redis is None:
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                raise RuntimeError("Redis is required for auth sessions")
            return

        now = int(time.time())
        user_id = str(getattr(user, "id", "") or "")
        session_payload = {
            "session_id": session_id,
            "user_id": user_id,
            "email": str(getattr(user, "email", "") or "").strip().lower(),
            "account_type": str(getattr(user, "account_type", "") or ""),
            "session_type": str(session_type or "user"),
            "scopes": [str(scope) for scope in scopes if scope],
            "fingerprint": self.fingerprint_request(request),
            "ip_address": self._client_ip(request),
            "created_at": utc_now().isoformat(),
            "last_seen_epoch": now,
        }
        ttl = max(60, int(ttl_seconds))
        key = self._session_key(session_id)
        user_key = self._user_sessions_key(user_id)
        try:
            await redis.setex(key, ttl, json.dumps(session_payload, separators=(",", ":")))
            await redis.sadd(user_key, session_id)
            await redis.expire(user_key, ttl)
        except Exception:
            logger.exception("Failed to persist auth session")
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                raise

    async def validate_session(
        self,
        *,
        user: User,
        session_id: str | None,
        request: Request | None,
    ) -> SessionValidationResult:
        if not settings.AUTH_SESSION_STORE_ENABLED:
            return SessionValidationResult(True)
        if not session_id:
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                return SessionValidationResult(False, "session_id_missing")
            return SessionValidationResult(True, "legacy_token")

        redis = get_redis()
        if redis is None:
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                return SessionValidationResult(False, "session_store_unavailable")
            return SessionValidationResult(True, "session_store_unavailable")

        try:
            raw = await redis.get(self._session_key(session_id))
        except Exception:
            logger.exception("Failed to read auth session")
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                return SessionValidationResult(False, "session_store_error")
            return SessionValidationResult(True, "session_store_error")

        if raw is None:
            if settings.AUTH_SESSION_REQUIRE_SERVER_STATE:
                return SessionValidationResult(False, "session_not_found")
            return SessionValidationResult(True, "session_not_found")

        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
        except Exception:
            return SessionValidationResult(False, "session_payload_invalid")

        if str(payload.get("user_id") or "") != str(getattr(user, "id", "") or ""):
            return SessionValidationResult(False, "session_user_mismatch")

        if settings.AUTH_SESSION_BIND_DEVICE:
            current_fingerprint = self.fingerprint_request(request)
            if str(payload.get("fingerprint") or "") != current_fingerprint:
                await self._audit_session_anomaly(user=user, request=request, reason="device_fingerprint_mismatch")
                return SessionValidationResult(False, "device_fingerprint_mismatch")

        await self._touch_session(redis=redis, session_id=session_id, payload=payload)
        return SessionValidationResult(True)

    async def invalidate_session(self, session_id: str | None) -> None:
        candidate = str(session_id or "").strip()
        if not candidate:
            return
        redis = get_redis()
        if redis is None:
            return
        try:
            raw = await redis.get(self._session_key(candidate))
            if raw:
                payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
                user_id = str(payload.get("user_id") or "").strip()
                if user_id:
                    await redis.srem(self._user_sessions_key(user_id), candidate)
            await redis.delete(self._session_key(candidate))
        except Exception:
            logger.exception("Failed to invalidate auth session")

    async def invalidate_user_sessions(self, user_id: str, *, keep_session_id: str | None = None) -> int:
        redis = get_redis()
        if redis is None:
            return 0
        user_key = self._user_sessions_key(user_id)
        try:
            members = await redis.smembers(user_key)
        except Exception:
            logger.exception("Failed to list user auth sessions")
            return 0
        count = 0
        keep = str(keep_session_id or "").strip()
        for member in members or []:
            session_id = member.decode("utf-8") if isinstance(member, (bytes, bytearray)) else str(member)
            if keep and session_id == keep:
                continue
            await redis.delete(self._session_key(session_id))
            await redis.srem(user_key, session_id)
            count += 1
        return count

    async def _touch_session(self, *, redis: Any, session_id: str, payload: dict[str, Any]) -> None:
        now = int(time.time())
        last_seen = int(payload.get("last_seen_epoch") or 0)
        interval = max(0, int(settings.AUTH_SESSION_ACTIVITY_UPDATE_INTERVAL_SECONDS))
        if interval and now - last_seen < interval:
            return
        payload["last_seen_epoch"] = now
        try:
            ttl = await redis.ttl(self._session_key(session_id))
            if int(ttl or 0) > 0:
                await redis.setex(self._session_key(session_id), int(ttl), json.dumps(payload, separators=(",", ":")))
        except Exception:
            logger.debug("Failed to touch auth session", exc_info=True)

    async def _audit_session_anomaly(self, *, user: User, request: Request | None, reason: str) -> None:
        await auth_security_service.audit_event(
            event_type="session.anomaly",
            email=str(getattr(user, "email", "") or "").strip().lower(),
            account_type=str(getattr(user, "account_type", "") or ""),
            purpose="signin",
            success=False,
            reason=reason,
            ip_address=self._client_ip(request),
            user_agent=(request.headers.get("user-agent") if request is not None else None),
            user_id=getattr(user, "id", None),
        )

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix()}:session:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"{self._prefix()}:user:{user_id}:sessions"

    def _prefix(self) -> str:
        return str(settings.AUTH_SESSION_REDIS_PREFIX or "vidyaverse:auth").strip().rstrip(":")

    def _client_ip(self, request: Request | None) -> str:
        if request is None:
            return "unknown"
        forwarded = request.headers.get("x-forwarded-for") or ""
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
        if request.client and request.client.host:
            return str(request.client.host)
        return "unknown"

    def _ip_prefix(self, value: str) -> str:
        candidate = str(value or "").strip()
        if not candidate or candidate == "unknown":
            return "unknown"
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            return "unknown"
        if ip.version == 4:
            network = ipaddress.ip_network(f"{ip}/24", strict=False)
        else:
            network = ipaddress.ip_network(f"{ip}/64", strict=False)
        return str(network.network_address)


session_security_service = SessionSecurityService()
