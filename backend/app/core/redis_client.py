from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import math

import pymongo.errors

from app.core.config import settings
from app.models.otp_code import OTPCode
from app.core.time import utc_now


# Alphanumeric codes, with the characters people misread removed: no 0/O, no
# 1/I/L. A six-character code from this alphabet is ~31^6, roughly 900 million
# combinations against 1 million for six digits, so it is also materially harder
# to guess inside the five-minute window.
OTP_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_OTP_DIGITS = "23456789"
_OTP_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ"
OTP_LENGTH = 6


def generate_otp(length: int = OTP_LENGTH) -> str:
    """A code guaranteed to contain at least one digit and one letter.

    Drawing purely at random would occasionally produce all-letter or all-digit
    codes, which look like a bug to anyone told to expect a mix.
    """
    import secrets as _secrets

    size = max(4, int(length))
    chars = [_secrets.choice(_OTP_DIGITS), _secrets.choice(_OTP_LETTERS)]
    chars += [_secrets.choice(OTP_ALPHABET) for _ in range(size - 2)]
    # SystemRandom().shuffle rather than a hand-rolled swap over randbelow: the
    # latter shares a function the auth tests patch to force a fixed code, and a
    # patched return value became an out-of-range index here.
    _secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def normalize_otp_input(value: str) -> str:
    """Reduce whatever the user submitted to a comparable code.

    Keeps only characters from the alphabet and upper-cases them, so a code
    pasted from an HTML email - which can carry a zero-width space - and one
    typed in lower case both match what was issued.
    """
    import re as _re

    return _re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_purpose(purpose: str) -> str:
    return purpose.strip().lower()


def _hash_otp(email: str, otp: str, purpose: str) -> str:
    # Upper-cased so case never decides whether a correct code is accepted.
    # Digit-only codes issued before this change hash identically.
    payload = f"{_normalize_email(email)}:{_normalize_purpose(purpose)}:{str(otp or '').upper()}:{settings.SECRET_KEY}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    expires_at = _as_utc_aware(record.expires_at)
    created_at = _as_utc_aware(record.created_at)
    if expires_at <= now:
        await record.delete()
        return 0

    elapsed = max(0.0, (now - created_at).total_seconds())
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

    if _as_utc_aware(record.expires_at) <= utc_now():
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
