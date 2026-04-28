from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from beanie import PydanticObjectId
from beanie.exceptions import CollectionWasNotInitialized
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.models.auth_abuse_state import AuthAbuseState
from app.models.auth_audit_event import AuthAuditEvent
from app.core.time import utc_now


@dataclass(frozen=True)
class AuthLockStatus:
    locked: bool
    lock_until: Optional[datetime]
    failed_attempts: int
    max_failed_attempts: int
    remaining_lock_seconds: int


class AuthSecurityService:
    def _state_key(self, *, email: str, action: str, purpose: str) -> str:
        normalized_email = (email or "").strip().lower()
        normalized_action = (action or "").strip().lower()
        normalized_purpose = (purpose or "signin").strip().lower()
        return f"{normalized_action}:{normalized_purpose}:{normalized_email}"

    async def check_lock(self, *, email: str, action: str, purpose: str = "signin") -> AuthLockStatus:
        now = utc_now()
        key = self._state_key(email=email, action=action, purpose=purpose)
        try:
            state = await AuthAbuseState.find_one(AuthAbuseState.key == key)
        except CollectionWasNotInitialized:
            state = None
        if not state:
            return AuthLockStatus(
                locked=False,
                lock_until=None,
                failed_attempts=0,
                max_failed_attempts=max(1, int(settings.AUTH_ABUSE_MAX_FAILED_ATTEMPTS)),
                remaining_lock_seconds=0,
            )

        lock_until = state.lock_until
        locked = bool(lock_until and lock_until > now)
        remaining = 0
        if locked and lock_until:
            remaining = max(0, int((lock_until - now).total_seconds()))
        return AuthLockStatus(
            locked=locked,
            lock_until=lock_until,
            failed_attempts=int(max(0, state.failed_attempts)),
            max_failed_attempts=max(1, int(settings.AUTH_ABUSE_MAX_FAILED_ATTEMPTS)),
            remaining_lock_seconds=remaining,
        )

    async def record_failure(self, *, email: str, action: str, purpose: str = "signin") -> AuthLockStatus:
        now = utc_now()
        window_seconds = max(30, int(settings.AUTH_ABUSE_WINDOW_SECONDS))
        lock_seconds = max(60, int(settings.AUTH_ABUSE_LOCK_SECONDS))
        max_attempts = max(1, int(settings.AUTH_ABUSE_MAX_FAILED_ATTEMPTS))
        key = self._state_key(email=email, action=action, purpose=purpose)

        try:
            state = await AuthAbuseState.find_one(AuthAbuseState.key == key)
        except CollectionWasNotInitialized:
            # During isolated unit tests, Beanie collections may be intentionally uninitialized.
            failed_attempts = 1
            locked = failed_attempts >= max_attempts
            lock_until = now + timedelta(seconds=lock_seconds) if locked else None
            return AuthLockStatus(
                locked=locked,
                lock_until=lock_until,
                failed_attempts=failed_attempts,
                max_failed_attempts=max_attempts,
                remaining_lock_seconds=lock_seconds if locked else 0,
            )
        if not state:
            state = AuthAbuseState(
                key=key,
                email=(email or "").strip().lower(),
                action=(action or "").strip().lower(),
                purpose=(purpose or "signin").strip().lower(),
                failed_attempts=1,
                first_failed_at=now,
                last_failed_at=now,
                lock_until=None,
                updated_at=now,
            )
            try:
                await state.insert()
            except DuplicateKeyError:
                state = await AuthAbuseState.find_one(AuthAbuseState.key == key)
                if not state:
                    raise
        else:
            reset_window = state.first_failed_at < (now - timedelta(seconds=window_seconds))
            if reset_window:
                state.failed_attempts = 1
                state.first_failed_at = now
            else:
                state.failed_attempts = int(max(0, state.failed_attempts)) + 1
            state.last_failed_at = now
            state.updated_at = now

        if int(max(0, state.failed_attempts)) >= max_attempts:
            state.lock_until = now + timedelta(seconds=lock_seconds)
        await state.save()

        status = await self.check_lock(email=email, action=action, purpose=purpose)
        return status

    async def record_success(self, *, email: str, action: str, purpose: str = "signin") -> None:
        key = self._state_key(email=email, action=action, purpose=purpose)
        try:
            state = await AuthAbuseState.find_one(AuthAbuseState.key == key)
        except CollectionWasNotInitialized:
            return
        if not state:
            return
        await state.delete()

    async def audit_event(
        self,
        *,
        event_type: str,
        email: str | None,
        account_type: str | None = None,
        purpose: str | None = None,
        success: bool,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        user_id: PydanticObjectId | None = None,
        lock_applied: bool = False,
        lock_until: datetime | None = None,
    ) -> None:
        if not bool(settings.AUTH_AUDIT_ENABLED):
            return
        try:
            event = AuthAuditEvent(
                event_type=(event_type or "unknown").strip().lower(),
                email=((email or "").strip().lower() or None),
                account_type=((account_type or "").strip().lower() or None),
                purpose=((purpose or "").strip().lower() or None),
                success=bool(success),
                reason=(reason or None),
                ip_address=((ip_address or "").strip() or None),
                user_agent=(user_agent or None),
                user_id=user_id,
                lock_applied=bool(lock_applied),
                lock_until=lock_until,
            )
            await event.insert()
        except CollectionWasNotInitialized:
            return


auth_security_service = AuthSecurityService()
