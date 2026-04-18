from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac

import pymongo.errors

from app.core.config import settings
from app.models.otp_code import OTPCode


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
    now = datetime.utcnow()
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


async def get_otp(email: str, purpose: str = "signin") -> str | None:
    normalized_email = _normalize_email(email)
    normalized_purpose = _normalize_purpose(purpose)

    record = await OTPCode.find_one(
        OTPCode.email == normalized_email,
        OTPCode.purpose == normalized_purpose,
    )
    if not record:
        return None

    if record.expires_at <= datetime.utcnow():
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
