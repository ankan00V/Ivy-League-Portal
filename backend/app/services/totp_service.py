from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_BASE32_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def _fernet() -> Fernet:
    key_material = hashlib.sha256(str(settings.SECRET_KEY or "").encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(key_material)
    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    normalized = normalize_totp_secret(secret)
    return _fernet().encrypt(normalized.encode("utf-8")).decode("utf-8")


def decrypt_secret(secret_encrypted: str) -> str:
    try:
        decrypted = _fernet().decrypt(str(secret_encrypted or "").encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid TOTP secret encryption payload") from exc
    return normalize_totp_secret(decrypted)


def normalize_totp_secret(value: str) -> str:
    candidate = str(value or "").strip().replace(" ", "").upper()
    if not candidate:
        raise ValueError("TOTP secret cannot be empty")
    if any(char not in _BASE32_ALPHABET for char in candidate):
        raise ValueError("TOTP secret must be a valid base32 string")
    return candidate


def generate_totp_secret(length_bytes: int = 20) -> str:
    raw = secrets.token_bytes(max(10, int(length_bytes)))
    return base64.b32encode(raw).decode("utf-8").rstrip("=")


def _int_to_bytes(value: int) -> bytes:
    return struct.pack(">Q", int(value))


def _hotp(secret_base32: str, counter: int, digits: int = 6) -> str:
    normalized = normalize_totp_secret(secret_base32)
    padding = "=" * (-len(normalized) % 8)
    secret = base64.b32decode((normalized + padding).encode("utf-8"), casefold=True)
    digest = hmac.new(secret, _int_to_bytes(counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    modulo = 10 ** max(6, int(digits))
    code = code_int % modulo
    return str(code).zfill(max(6, int(digits)))


def verify_totp(
    *,
    secret_base32: str,
    code: str,
    at_time: Optional[int] = None,
    period_seconds: Optional[int] = None,
    digits: Optional[int] = None,
    window_steps: Optional[int] = None,
) -> bool:
    normalized_code = str(code or "").strip()
    totp_digits = max(6, int(digits or settings.ADMIN_TOTP_DIGITS))
    if len(normalized_code) != totp_digits or not normalized_code.isdigit():
        return False

    secret = normalize_totp_secret(secret_base32)
    now = int(at_time if at_time is not None else time.time())
    period = max(15, int(period_seconds or settings.ADMIN_TOTP_PERIOD_SECONDS))
    window = max(0, int(window_steps if window_steps is not None else settings.ADMIN_TOTP_WINDOW_STEPS))

    counter = now // period
    for offset in range(-window, window + 1):
        candidate_counter = counter + offset
        if candidate_counter < 0:
            continue
        if hmac.compare_digest(_hotp(secret, candidate_counter, digits=totp_digits), normalized_code):
            return True
    return False


@dataclass(frozen=True)
class TotpProvisioning:
    secret: str
    issuer: str
    account_name: str
    uri: str


def provisioning_uri(*, secret_base32: str, account_name: str, issuer: Optional[str] = None) -> TotpProvisioning:
    normalized_secret = normalize_totp_secret(secret_base32)
    issuer_value = (issuer or settings.ADMIN_TOTP_ISSUER or "Vidyaverse").strip() or "Vidyaverse"
    account_value = str(account_name or "").strip().lower()
    if not account_value:
        raise ValueError("account_name is required")
    label = quote(f"{issuer_value}:{account_value}")
    issuer_q = quote(issuer_value)
    uri = (
        f"otpauth://totp/{label}"
        f"?secret={normalized_secret}"
        f"&issuer={issuer_q}"
        f"&algorithm=SHA1"
        f"&digits={max(6, int(settings.ADMIN_TOTP_DIGITS))}"
        f"&period={max(15, int(settings.ADMIN_TOTP_PERIOD_SECONDS))}"
    )
    return TotpProvisioning(
        secret=normalized_secret,
        issuer=issuer_value,
        account_name=account_value,
        uri=uri,
    )
