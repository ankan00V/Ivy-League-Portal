from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import math

import pymongo.errors

from app.core.config import settings
from app.models.otp_code import OTPCode
from app.core.time import utc_now


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_purpose(purpose: str) -> str:
    return purpose.strip().lower()


def _hash_otp(email: str, otp: str, purpose: str) -> str:
    payload = f"{_normalize_email(email)}:{_normalize_purpose(purpose)}:{otp}:{settings.SECRET_KEY}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def set_otp(
    email: str,
    otp: str,
    expire_seconds: int = 300,
    purpose: str = "signin",
) -> None:
    normalized_email = _normalize_email(email)
    normalized_purpose = _normalize_purpose(purpose)
    now = utc_now()
    expires_at = now + timedelta(seconds=max(30, expire_seconds))
    otp_hash = _hash_otp(normalized_email, otp, normalized_purpose)

    record = await OTPCode.find_one(
        OTPCode.email == normalized_email,
        OTPCode.purpose == normalized_purpose,
    )
    if record:
        record.otp_hash = otp_hash
        record.expires_at = expires_at
        record.created_at = now
        await record.save()
        return

    try:
        await OTPCode(
            email=normalized_email,
            purpose=normalized_purpose,
            otp_hash=otp_hash,
            expires_at=expires_at,
            created_at=now,
        ).insert()
    except pymongo.errors.DuplicateKeyError:
        # Handle racing requests safely when the unique (email, purpose) row was created concurrently.
        record = await OTPCode.find_one(
            OTPCode.email == normalized_email,
            OTPCode.purpose == normalized_purpose,
        )
        if record:
            record.otp_hash = otp_hash
            record.expires_at = expires_at
            record.created_at = now
            await record.save()


async def get_otp_cooldown_remaining(
    email: str,
    *,
    purpose: str = "signin",
    cooldown_seconds: int = 60,
) -> int:
    normalized_email = _normalize_email(email)
    normalized_purpose = _normalize_purpose(purpose)
    safe_cooldown = max(1, int(cooldown_seconds))

    record = await OTPCode.find_one(
        OTPCode.email == normalized_email,
        OTPCode.purpose == normalized_purpose,
    )
    if not record:
        return 0

    now = utc_now()
    if record.expires_at <= now:
        await record.delete()
        return 0

    elapsed = max(0.0, (now - record.created_at).total_seconds())
    remaining = int(math.ceil(safe_cooldown - elapsed))
    return max(0, remaining)


async def get_otp(email: str, purpose: str = "signin") -> str | None:
    normalized_email = _normalize_email(email)
    normalized_purpose = _normalize_purpose(purpose)

    record = await OTPCode.find_one(
        OTPCode.email == normalized_email,
        OTPCode.purpose == normalized_purpose,
    )
    if not record:
        return None

    if record.expires_at <= utc_now():
        await record.delete()
        return None

    return record.otp_hash


async def validate_otp(email: str, otp: str, purpose: str = "signin") -> bool:
    stored_hash = await get_otp(email, purpose=purpose)
    if not stored_hash:
        return False

    provided_hash = _hash_otp(email, otp, purpose)
    return hmac.compare_digest(stored_hash, provided_hash)


async def delete_otp(email: str, purpose: str = "signin") -> None:
    normalized_email = _normalize_email(email)
    normalized_purpose = _normalize_purpose(purpose)
    record = await OTPCode.find_one(
        OTPCode.email == normalized_email,
        OTPCode.purpose == normalized_purpose,
    )
    if record:
        await record.delete()
