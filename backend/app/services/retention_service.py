"""Deletes rows that used to expire on their own.

MongoDB removed these automatically via TTL indexes: OTP codes at their
`expires_at`, and auth audit events after ninety days. Postgres has no
equivalent, and Neon does not permit pg_cron outside the `postgres` database, so
the expiry has to become an explicit job.

This is the kind of thing that fails quietly. Nothing errors when expired OTPs
stop being deleted - they simply accumulate, and a code that should have died in
ten minutes stays valid in the table indefinitely. So the job reports what it
deleted on every run rather than only on failure, and the retention windows are
read from settings rather than hard-coded, so shortening them is a config change
rather than a deploy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.core.time import utc_now

logger = logging.getLogger(__name__)


@dataclass
class RetentionReport:
    otp_deleted: int = 0
    audit_deleted: int = 0
    sessions_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "otp_deleted": self.otp_deleted,
            "audit_deleted": self.audit_deleted,
            "sessions_deleted": self.sessions_deleted,
            "errors": self.errors[:5],
            "total_deleted": self.otp_deleted + self.audit_deleted + self.sessions_deleted,
        }


async def purge_expired_records() -> dict[str, Any]:
    """Delete what the TTL indexes used to delete.

    Written against the Mongo models because they are still the source of truth
    during the migration. The same windows apply once the tables move to
    Postgres; only the delete statements change.
    """
    report = RetentionReport()
    if not settings.RETENTION_PURGE_ENABLED:
        return {**report.as_dict(), "status": "disabled"}

    now = utc_now()

    # OTP codes: Mongo expired these the moment `expires_at` passed. A stale
    # verification code is a live credential, so this is the one that matters.
    try:
        from app.models.otp_code import OTPCode

        result = await OTPCode.find(OTPCode.expires_at < now).delete()
        report.otp_deleted = int(getattr(result, "deleted_count", 0) or 0)
    except Exception as exc:
        report.errors.append(f"otp: {type(exc).__name__}: {exc}"[:160])
        logger.warning("otp retention purge failed", exc_info=True)

    # Auth audit events: ninety days, matching the TTL index that was declared
    # on the model.
    try:
        from app.models.auth_audit_event import AuthAuditEvent

        cutoff = now - timedelta(days=max(1, int(settings.AUTH_AUDIT_RETENTION_DAYS)))
        result = await AuthAuditEvent.find(AuthAuditEvent.created_at < cutoff).delete()
        report.audit_deleted = int(getattr(result, "deleted_count", 0) or 0)
    except Exception as exc:
        report.errors.append(f"audit: {type(exc).__name__}: {exc}"[:160])
        logger.warning("auth audit retention purge failed", exc_info=True)

    # Sessions are held in Redis, which expires them itself, so there is no
    # durable session table to sweep here. Left as a named zero rather than
    # removed, so the report shape does not change if one is added later.

    payload = report.as_dict()
    # Logged at info on every run, not just on failure: silent success is
    # indistinguishable from silent breakage for a job like this.
    logger.info("retention purge complete", extra={"retention": payload})
    return payload
