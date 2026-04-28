from __future__ import annotations

import base64
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, field_validator

from app.api.deps import get_current_admin_user
from app.core.config import auth_cookie_only_mode_enabled, settings
from app.core.email_policy import is_corporate_email
from app.core.redis_client import delete_otp, get_otp_cooldown_remaining, set_otp, validate_otp
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.auth_abuse_state import AuthAbuseState
from app.models.auth_audit_event import AuthAuditEvent
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse
from app.services.admin_identity_service import is_reserved_admin_email
from app.services.auth_security_service import auth_security_service
from app.services.email import send_email_otp
from app.services.totp_service import decrypt_secret, provisioning_uri, verify_totp
from app.services.username_service import ensure_system_username
from app.core.time import utc_now

router = APIRouter()
logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 300
ADMIN_CHALLENGE_EXPIRY_SECONDS = 600
ADMIN_TOTP_STEP_EXPIRY_SECONDS = 600
LOCAL_ENV_NAMES = {"local", "dev", "development", "test"}
VALID_ACCOUNT_TYPES = {"candidate", "employer"}
LOCAL_OAUTH_HOSTS = {"localhost", "127.0.0.1"}
COOKIE_SESSION_SENTINEL = "__cookie_session__"
ADMIN_CHALLENGE_SCOPE = "admin:challenge"
ADMIN_TOTP_SCOPE = "admin:totp"


def _scopes_for_user(user: User) -> list[str]:
    scopes = ["user"]
    if bool(getattr(user, "is_admin", False)) and is_reserved_admin_email(getattr(user, "email", "")):
        scopes.extend(["admin", "metrics:read", "jobs:read", "jobs:write", "scraper:trigger"])
    return scopes


def _normalize_account_type(value: Optional[str], *, default: str = "candidate") -> str:
    candidate = str(value or default).strip().lower()
    if candidate not in VALID_ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail="account_type must be candidate or employer")
    return candidate


def _ensure_employer_corporate_email(email: str) -> None:
    if not is_corporate_email(email):
        raise HTTPException(
            status_code=400,
            detail="Employer signup/login requires a corporate email (personal providers are not allowed).",
        )


def _base64url_encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
    payload = json.loads(decoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("state payload must be an object")
    return payload


def _append_query(url: str, params: dict[str, str]) -> str:
    split = urlsplit(url)
    existing = split.query
    append = urlencode(params)
    query = f"{existing}&{append}" if existing else append
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _sanitize_next_path(value: Optional[str]) -> str:
    candidate = (value or "").strip()
    if not candidate.startswith("/"):
        return "/dashboard"
    if candidate.startswith("//"):
        return "/dashboard"
    return candidate


def _normalize_frontend_origin(value: Optional[str]) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    split = urlsplit(candidate)
    if split.scheme not in {"http", "https"} or not split.netloc:
        return None
    if split.path not in {"", "/"} or split.query or split.fragment:
        return None
    return urlunsplit((split.scheme, split.netloc, "", "", ""))


def _normalize_url(value: Optional[str]) -> Optional[tuple[str, str, str, str]]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    split = urlsplit(candidate)
    if split.scheme not in {"http", "https"} or not split.netloc:
        return None
    return split.scheme, split.netloc, split.path or "/", split.query


def _replace_netloc(url: str, netloc: str) -> str:
    split = urlsplit(url)
    return urlunsplit((split.scheme, netloc, split.path, split.query, split.fragment))


def _frontend_host_and_port(frontend_origin: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    normalized = _normalize_frontend_origin(frontend_origin)
    if not normalized:
        return None, None
    split = urlsplit(normalized)
    return split.hostname, split.port


def _resolve_google_redirect_uri(frontend_origin: Optional[str]) -> str:
    configured = (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    if not configured:
        return configured

    parsed = urlsplit(configured)
    configured_host = parsed.hostname
    if configured_host not in LOCAL_OAUTH_HOSTS:
        return configured

    frontend_host, _frontend_port = _frontend_host_and_port(frontend_origin)
    if frontend_host not in LOCAL_OAUTH_HOSTS or frontend_host == configured_host:
        return configured

    port = parsed.port
    replacement_netloc = frontend_host if port is None else f"{frontend_host}:{port}"
    return _replace_netloc(configured, replacement_netloc)


def _is_allowed_google_redirect_uri(candidate: Optional[str]) -> bool:
    normalized_candidate = _normalize_url(candidate)
    normalized_configured = _normalize_url(settings.GOOGLE_OAUTH_REDIRECT_URI)
    if not normalized_candidate or not normalized_configured:
        return False
    if normalized_candidate == normalized_configured:
        return True

    candidate_scheme, candidate_netloc, candidate_path, candidate_query = normalized_candidate
    configured_scheme, configured_netloc, configured_path, configured_query = normalized_configured
    candidate_split = urlsplit(candidate or "")
    configured_split = urlsplit(settings.GOOGLE_OAUTH_REDIRECT_URI or "")

    return (
        candidate_scheme == configured_scheme
        and candidate_path == configured_path
        and candidate_query == configured_query
        and candidate_split.hostname in LOCAL_OAUTH_HOSTS
        and configured_split.hostname in LOCAL_OAUTH_HOSTS
        and candidate_split.port == configured_split.port
        and candidate_netloc != configured_netloc
    )


def _join_origin_path(origin: str, path: str, *, default_path: str) -> str:
    normalized_path = (path or "").strip() or default_path
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    return f"{origin.rstrip('/')}{normalized_path}"


def _resolve_oauth_frontend_urls(frontend_origin: Optional[str]) -> tuple[str, str]:
    success_url = settings.FRONTEND_OAUTH_SUCCESS_URL
    failure_url = settings.FRONTEND_OAUTH_FAILURE_URL
    normalized_origin = _normalize_frontend_origin(frontend_origin)
    if not normalized_origin:
        return success_url, failure_url

    success_path = urlsplit(success_url).path or "/auth/callback"
    failure_path = urlsplit(failure_url).path or "/login"
    return (
        _join_origin_path(normalized_origin, success_path, default_path="/auth/callback"),
        _join_origin_path(normalized_origin, failure_path, default_path="/login"),
    )


def _google_oauth_is_configured() -> bool:
    return bool(
        (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
        and (settings.GOOGLE_OAUTH_CLIENT_SECRET or "").strip()
        and (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    )


def _request_context(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    ip_address: Optional[str] = None
    if request.client and request.client.host:
        ip_address = str(request.client.host)
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


def _reject_reserved_admin_identity_for_public_auth(email: str) -> None:
    if is_reserved_admin_email(email):
        raise HTTPException(
            status_code=403,
            detail="This identity uses the dedicated admin authentication flow.",
        )


def _validate_admin_totp_or_raise(user: User, code: str) -> None:
    encrypted_secret = str(getattr(user, "totp_secret_encrypted", "") or "").strip()
    if not encrypted_secret:
        raise HTTPException(status_code=503, detail="Admin TOTP is not configured")
    try:
        secret = decrypt_secret(encrypted_secret)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Admin TOTP is unavailable") from exc
    if not verify_totp(secret_base32=secret, code=code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")


def _set_session_cookie(response: Optional[Response], token: str) -> None:
    if response is None:
        return
    if not settings.AUTH_SESSION_COOKIE_ENABLED:
        return
    cookie_name = (settings.AUTH_SESSION_COOKIE_NAME or "").strip()
    if not cookie_name:
        return
    same_site = str(settings.AUTH_SESSION_COOKIE_SAMESITE or "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"

    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max(60, int(settings.AUTH_SESSION_COOKIE_MAX_AGE_SECONDS)),
        httponly=True,
        secure=bool(settings.AUTH_SESSION_COOKIE_SECURE),
        samesite=same_site,
        path=(settings.AUTH_SESSION_COOKIE_PATH or "/").strip() or "/",
        domain=(settings.AUTH_SESSION_COOKIE_DOMAIN or "").strip() or None,
    )


def _public_access_token(token: str) -> str:
    if auth_cookie_only_mode_enabled():
        return COOKIE_SESSION_SENTINEL
    return token


def _token_response_payload(token: str) -> dict[str, str]:
    return {"access_token": _public_access_token(token), "token_type": "bearer"}


def _clear_session_cookie(response: Optional[Response]) -> None:
    if response is None:
        return
    cookie_name = (settings.AUTH_SESSION_COOKIE_NAME or "").strip()
    if not cookie_name:
        return
    response.delete_cookie(
        key=cookie_name,
        path=(settings.AUTH_SESSION_COOKIE_PATH or "/").strip() or "/",
        domain=(settings.AUTH_SESSION_COOKIE_DOMAIN or "").strip() or None,
    )


class PasswordLoginResponse(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    requires_admin_verification: bool = False
    admin_challenge_token: str | None = None
    admin_verification_path: str | None = None
    otp_delivery: Literal["email", "debug"] | None = None
    otp_expires_in_seconds: int | None = None
    otp_cooldown_seconds: int | None = None
    debug_otp: str | None = None
    totp_setup_required: bool = False
    totp_setup_secret: str | None = None
    totp_setup_uri: str | None = None
    totp_setup_issuer: str | None = None
    totp_setup_account_name: str | None = None


def _admin_totp_setup_payload(user: User) -> dict[str, Any]:
    if bool(getattr(user, "totp_enabled", False)):
        return {"totp_setup_required": False}

    encrypted_secret = str(getattr(user, "totp_secret_encrypted", "") or "").strip()
    if not encrypted_secret:
        raise HTTPException(status_code=503, detail="Admin TOTP is not configured")

    try:
        secret = decrypt_secret(encrypted_secret)
        setup = provisioning_uri(secret_base32=secret, account_name=str(getattr(user, "email", "") or "").strip().lower())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Admin TOTP setup is unavailable") from exc

    return {
        "totp_setup_required": True,
        "totp_setup_secret": setup.secret,
        "totp_setup_uri": setup.uri,
        "totp_setup_issuer": setup.issuer,
        "totp_setup_account_name": setup.account_name,
    }


class AdminVerifyRequest(BaseModel):
    email: EmailStr
    otp: str
    totp_code: str
    admin_challenge_token: str

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_otp(cls, value: str) -> str:
        otp = str(value or "").strip()
        if len(otp) != 6 or not otp.isdigit():
            raise ValueError("OTP must be a 6-digit numeric code")
        return otp

    @field_validator("totp_code", mode="before")
    @classmethod
    def normalize_totp_code(cls, value: str) -> str:
        code = str(value or "").strip()
        if not code.isdigit() or len(code) != max(6, int(settings.ADMIN_TOTP_DIGITS)):
            raise ValueError(f"TOTP code must be a {max(6, int(settings.ADMIN_TOTP_DIGITS))}-digit number")
        return code

    @field_validator("admin_challenge_token", mode="before")
    @classmethod
    def normalize_admin_challenge_token(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("admin_challenge_token is required")
        return token


class AdminResendOtpRequest(BaseModel):
    email: EmailStr
    admin_challenge_token: str

    @field_validator("admin_challenge_token", mode="before")
    @classmethod
    def normalize_admin_challenge_token(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("admin_challenge_token is required")
        return token


class AdminResendOtpResponse(BaseModel):
    message: str
    delivery: Literal["email", "debug"]
    expires_in_seconds: int = OTP_EXPIRY_SECONDS
    cooldown_seconds: int = 60
    debug_otp: str | None = None


class AdminOtpVerifyRequest(BaseModel):
    email: EmailStr
    otp: str
    admin_challenge_token: str

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_otp(cls, value: str) -> str:
        otp = str(value or "").strip()
        if len(otp) != 6 or not otp.isdigit():
            raise ValueError("OTP must be a 6-digit numeric code")
        return otp

    @field_validator("admin_challenge_token", mode="before")
    @classmethod
    def normalize_admin_challenge_token(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("admin_challenge_token is required")
        return token


class AdminOtpVerifyResponse(BaseModel):
    message: str
    admin_totp_token: str


class AdminTotpVerifyRequest(BaseModel):
    email: EmailStr
    totp_code: str
    admin_totp_token: str

    @field_validator("totp_code", mode="before")
    @classmethod
    def normalize_totp_code(cls, value: str) -> str:
        code = str(value or "").strip()
        if not code.isdigit() or len(code) != max(6, int(settings.ADMIN_TOTP_DIGITS)):
            raise ValueError(f"TOTP code must be a {max(6, int(settings.ADMIN_TOTP_DIGITS))}-digit number")
        return code

    @field_validator("admin_totp_token", mode="before")
    @classmethod
    def normalize_admin_totp_token(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("admin_totp_token is required")
        return token


def _create_admin_challenge_token(user: User) -> str:
    return create_access_token(
        str(user.id),
        expires_delta=timedelta(seconds=ADMIN_CHALLENGE_EXPIRY_SECONDS),
        scopes=[ADMIN_CHALLENGE_SCOPE],
    )


def _create_admin_totp_token(user: User) -> str:
    return create_access_token(
        str(user.id),
        expires_delta=timedelta(seconds=ADMIN_TOTP_STEP_EXPIRY_SECONDS),
        scopes=[ADMIN_TOTP_SCOPE],
    )


def _decode_admin_challenge_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired admin verification session") from exc

    subject = str(payload.get("sub") or "").strip()
    raw_scopes = payload.get("scopes") or []
    scopes = [str(scope) for scope in raw_scopes] if isinstance(raw_scopes, list) else [str(raw_scopes)]
    if not subject or ADMIN_CHALLENGE_SCOPE not in scopes:
        raise HTTPException(status_code=401, detail="Invalid or expired admin verification session")
    return subject


def _decode_admin_totp_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired admin TOTP session") from exc

    subject = str(payload.get("sub") or "").strip()
    raw_scopes = payload.get("scopes") or []
    scopes = [str(scope) for scope in raw_scopes] if isinstance(raw_scopes, list) else [str(raw_scopes)]
    if not subject or ADMIN_TOTP_SCOPE not in scopes:
        raise HTTPException(status_code=401, detail="Invalid or expired admin TOTP session")
    return subject


async def _issue_admin_email_otp(email: str) -> tuple[Literal["email", "debug"], int, str | None]:
    cooldown_seconds = max(1, int(settings.OTP_SEND_COOLDOWN_SECONDS))
    remaining_cooldown = await get_otp_cooldown_remaining(
        email,
        purpose="signin",
        cooldown_seconds=cooldown_seconds,
    )
    if remaining_cooldown > 0:
        return "email", remaining_cooldown, None

    otp = f"{secrets.randbelow(1_000_000):06d}"
    await set_otp(
        email,
        otp,
        expire_seconds=OTP_EXPIRY_SECONDS,
        purpose="signin",
    )

    try:
        await send_email_otp(email, otp)
        return "email", cooldown_seconds, None
    except Exception:
        if str(settings.ENVIRONMENT).strip().lower() in LOCAL_ENV_NAMES and bool(settings.OTP_ALLOW_DEBUG_FALLBACK):
            return "debug", cooldown_seconds, otp
        await delete_otp(email, purpose="signin")
        raise


@router.post("/register", response_model=UserResponse)
async def register_user(
    user_in: UserCreate
) -> Any:
    """
    Create new user via password flow.
    """
    normalized_email = str(user_in.email or "").strip().lower()
    _reject_reserved_admin_identity_for_public_auth(normalized_email)
    user = await User.find_one(User.email == normalized_email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = User(
        email=normalized_email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        account_type="candidate",
        auth_provider="password",
    )
    await user.insert()
    await ensure_system_username(user)
    return user


@router.post("/login", response_model=PasswordLoginResponse)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    normalized_email = str(form_data.username or "").strip().lower()
    ip_address, user_agent = _request_context(request)

    lock = await auth_security_service.check_lock(email=normalized_email, action="password_login", purpose="signin")
    if lock.locked:
        await auth_security_service.audit_event(
            event_type="login.blocked",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="account_locked",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=True,
            lock_until=lock.lock_until,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {lock.remaining_lock_seconds} seconds.",
            headers={"Retry-After": str(max(1, lock.remaining_lock_seconds))},
        )

    user = await User.find_one(User.email == normalized_email)

    if not user or not verify_password(form_data.password, user.hashed_password):
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="password_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.password",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_credentials",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
        )
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        await auth_security_service.audit_event(
            event_type="login.password",
            email=normalized_email,
            account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
            purpose="signin",
            success=False,
            reason="inactive_user",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )
        raise HTTPException(status_code=400, detail="Inactive user")
    if is_reserved_admin_email(normalized_email):
        if not bool(getattr(user, "is_admin", False)):
            await auth_security_service.audit_event(
                event_type="login.admin",
                email=normalized_email,
                purpose="signin",
                success=False,
                reason="admin_identity_not_provisioned",
                ip_address=ip_address,
                user_agent=user_agent,
                user_id=user.id,
            )
            raise HTTPException(status_code=403, detail="Admin identity is not provisioned")

        try:
            delivery, otp_cooldown_seconds, debug_otp = await _issue_admin_email_otp(normalized_email)
        except Exception as exc:
            await auth_security_service.audit_event(
                event_type="login.admin",
                email=normalized_email,
                purpose="signin",
                success=False,
                reason="otp_delivery_failed",
                ip_address=ip_address,
                user_agent=user_agent,
                user_id=user.id,
            )
            raise HTTPException(status_code=503, detail=f"Unable to start admin verification: {exc}") from exc

        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
            purpose="signin",
            success=True,
            reason="password_verified_pending_otp_totp",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )
        return PasswordLoginResponse(
            requires_admin_verification=True,
            admin_challenge_token=_create_admin_challenge_token(user),
            admin_verification_path="/control/auth",
            otp_delivery=delivery,
            otp_expires_in_seconds=OTP_EXPIRY_SECONDS,
            otp_cooldown_seconds=otp_cooldown_seconds,
            debug_otp=debug_otp,
            **_admin_totp_setup_payload(user),
        )
    if str(getattr(user, "account_type", "candidate")).strip().lower() == "employer":
        _ensure_employer_corporate_email(user.email)

    await auth_security_service.record_success(email=normalized_email, action="password_login", purpose="signin")
    await auth_security_service.audit_event(
        event_type="login.password",
        email=normalized_email,
        account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
        purpose="signin",
        success=True,
        reason="ok",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        str(user.id),
        expires_delta=access_token_expires,
        scopes=_scopes_for_user(user),
    )
    _set_session_cookie(response, token)
    return _token_response_payload(token)


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str

    @field_validator("totp_code", mode="before")
    @classmethod
    def normalize_totp_code(cls, value: str) -> str:
        code = str(value or "").strip()
        if not code.isdigit() or len(code) != max(6, int(settings.ADMIN_TOTP_DIGITS)):
            raise ValueError(f"TOTP code must be a {max(6, int(settings.ADMIN_TOTP_DIGITS))}-digit number")
        return code


@router.post("/admin/verify", response_model=Token, include_in_schema=False)
async def verify_admin_access_token(
    payload: AdminVerifyRequest,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    normalized_email = str(payload.email or "").strip().lower()
    ip_address, user_agent = _request_context(request)
    if not is_reserved_admin_email(normalized_email):
        raise HTTPException(status_code=403, detail="Not authorized")

    challenge_user_id = _decode_admin_challenge_token(payload.admin_challenge_token)

    lock = await auth_security_service.check_lock(email=normalized_email, action="admin_login", purpose="signin")
    if lock.locked:
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="account_locked",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=True,
            lock_until=lock.lock_until,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {lock.remaining_lock_seconds} seconds.",
            headers={"Retry-After": str(max(1, lock.remaining_lock_seconds))},
        )

    user = await User.find_one(User.email == normalized_email)
    if not user or not bool(getattr(user, "is_admin", False)) or str(user.id) != challenge_user_id:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="admin_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_admin_challenge",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
            user_id=user.id if user else None,
        )
        raise HTTPException(status_code=400, detail="Invalid admin verification session")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    is_valid = await validate_otp(
        normalized_email,
        payload.otp,
        purpose="signin",
    )
    if not is_valid:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="admin_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_or_expired_otp",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
            user_id=user.id,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    try:
        _validate_admin_totp_or_raise(user, payload.totp_code)
    except HTTPException as exc:
        reason = "invalid_totp" if exc.status_code == 400 else "totp_unavailable"
        lock_applied = False
        lock_until = None
        if exc.status_code == 400:
            failure = await auth_security_service.record_failure(
                email=normalized_email,
                action="admin_login",
                purpose="signin",
            )
            lock_applied = failure.locked
            lock_until = failure.lock_until
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=lock_applied,
            lock_until=lock_until,
            user_id=user.id,
        )
        raise exc

    await delete_otp(normalized_email, purpose="signin")
    if not bool(getattr(user, "totp_enabled", False)):
        user.totp_enabled = True
        await user.save()
    await auth_security_service.record_success(email=normalized_email, action="admin_login", purpose="signin")
    await auth_security_service.audit_event(
        event_type="login.admin",
        email=normalized_email,
        account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
        purpose="signin",
        success=True,
        reason="ok",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        str(user.id),
        expires_delta=access_token_expires,
        scopes=_scopes_for_user(user),
    )
    _set_session_cookie(response, token)
    return _token_response_payload(token)


@router.post("/admin/resend-otp", response_model=AdminResendOtpResponse, include_in_schema=False)
async def resend_admin_otp(
    payload: AdminResendOtpRequest,
    request: Request = None,  # type: ignore[assignment]
) -> Any:
    normalized_email = str(payload.email or "").strip().lower()
    ip_address, user_agent = _request_context(request)
    if not is_reserved_admin_email(normalized_email):
        raise HTTPException(status_code=403, detail="Not authorized")

    challenge_user_id = _decode_admin_challenge_token(payload.admin_challenge_token)
    user = await User.find_one(User.email == normalized_email)
    if not user or not bool(getattr(user, "is_admin", False)) or str(user.id) != challenge_user_id:
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_admin_challenge_for_otp_resend",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id if user else None,
        )
        raise HTTPException(status_code=400, detail="Invalid admin verification session")

    try:
        delivery, cooldown_seconds, debug_otp = await _issue_admin_email_otp(normalized_email)
    except Exception as exc:
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="otp_redelivery_failed",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )
        raise HTTPException(status_code=503, detail=f"Unable to resend admin OTP: {exc}") from exc

    resent = bool(debug_otp) or cooldown_seconds == max(1, int(settings.OTP_SEND_COOLDOWN_SECONDS))
    await auth_security_service.audit_event(
        event_type="login.admin",
        email=normalized_email,
        purpose="signin",
        success=True,
        reason="otp_resent" if resent else "otp_resend_rate_limited",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )
    return AdminResendOtpResponse(
        message="A fresh OTP was sent to your email." if resent else f"OTP already sent. Retry in {cooldown_seconds}s.",
        delivery=delivery,
        expires_in_seconds=OTP_EXPIRY_SECONDS,
        cooldown_seconds=cooldown_seconds,
        debug_otp=debug_otp,
    )


@router.post("/admin/verify-otp", response_model=AdminOtpVerifyResponse, include_in_schema=False)
async def verify_admin_otp(
    payload: AdminOtpVerifyRequest,
    request: Request = None,  # type: ignore[assignment]
) -> Any:
    normalized_email = str(payload.email or "").strip().lower()
    ip_address, user_agent = _request_context(request)
    if not is_reserved_admin_email(normalized_email):
        raise HTTPException(status_code=403, detail="Not authorized")

    challenge_user_id = _decode_admin_challenge_token(payload.admin_challenge_token)
    lock = await auth_security_service.check_lock(email=normalized_email, action="admin_login", purpose="signin")
    if lock.locked:
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="account_locked",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=True,
            lock_until=lock.lock_until,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {lock.remaining_lock_seconds} seconds.",
            headers={"Retry-After": str(max(1, lock.remaining_lock_seconds))},
        )

    user = await User.find_one(User.email == normalized_email)
    if not user or not bool(getattr(user, "is_admin", False)) or str(user.id) != challenge_user_id:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="admin_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_admin_challenge",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
            user_id=user.id if user else None,
        )
        raise HTTPException(status_code=400, detail="Invalid admin verification session")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    is_valid = await validate_otp(normalized_email, payload.otp, purpose="signin")
    if not is_valid:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="admin_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_or_expired_otp",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
            user_id=user.id,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    await delete_otp(normalized_email, purpose="signin")
    await auth_security_service.audit_event(
        event_type="login.admin",
        email=normalized_email,
        account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
        purpose="signin",
        success=True,
        reason="otp_verified_pending_totp",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )
    return AdminOtpVerifyResponse(
        message="OTP verified. Enter your authenticator TOTP to continue.",
        admin_totp_token=_create_admin_totp_token(user),
    )


@router.post("/admin/verify-totp", response_model=Token, include_in_schema=False)
async def verify_admin_totp(
    payload: AdminTotpVerifyRequest,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    normalized_email = str(payload.email or "").strip().lower()
    ip_address, user_agent = _request_context(request)
    if not is_reserved_admin_email(normalized_email):
        raise HTTPException(status_code=403, detail="Not authorized")

    totp_user_id = _decode_admin_totp_token(payload.admin_totp_token)
    lock = await auth_security_service.check_lock(email=normalized_email, action="admin_login", purpose="signin")
    if lock.locked:
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="account_locked",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=True,
            lock_until=lock.lock_until,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {lock.remaining_lock_seconds} seconds.",
            headers={"Retry-After": str(max(1, lock.remaining_lock_seconds))},
        )

    user = await User.find_one(User.email == normalized_email)
    if not user or not bool(getattr(user, "is_admin", False)) or str(user.id) != totp_user_id:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="admin_login",
            purpose="signin",
        )
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason="invalid_admin_totp_session",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
            user_id=user.id if user else None,
        )
        raise HTTPException(status_code=400, detail="Invalid admin TOTP session")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    try:
        _validate_admin_totp_or_raise(user, payload.totp_code)
    except HTTPException as exc:
        reason = "invalid_totp" if exc.status_code == 400 else "totp_unavailable"
        lock_applied = False
        lock_until = None
        if exc.status_code == 400:
            failure = await auth_security_service.record_failure(
                email=normalized_email,
                action="admin_login",
                purpose="signin",
            )
            lock_applied = failure.locked
            lock_until = failure.lock_until
        await auth_security_service.audit_event(
            event_type="login.admin",
            email=normalized_email,
            purpose="signin",
            success=False,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=lock_applied,
            lock_until=lock_until,
            user_id=user.id,
        )
        raise exc

    if not bool(getattr(user, "totp_enabled", False)):
        user.totp_enabled = True
        await user.save()
    await auth_security_service.record_success(email=normalized_email, action="admin_login", purpose="signin")
    await auth_security_service.audit_event(
        event_type="login.admin",
        email=normalized_email,
        account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
        purpose="signin",
        success=True,
        reason="ok",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        str(user.id),
        expires_delta=access_token_expires,
        scopes=_scopes_for_user(user),
    )
    _set_session_cookie(response, token)
    return _token_response_payload(token)


@router.post("/admin/login", response_model=Token, include_in_schema=False)
async def login_admin_access_token(
    payload: AdminLoginRequest,
    request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    del payload, request, response
    raise HTTPException(
        status_code=410,
        detail="Start from the normal login page. Admin sign-in now requires password, email OTP, and TOTP.",
    )


class OTPSendRequest(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "signin"] = "signin"
    account_type: Optional[Literal["candidate", "employer"]] = None

    @field_validator("purpose", mode="before")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        return str(value).strip().lower()


class OTPSendResponse(BaseModel):
    message: str
    delivery: Literal["email", "debug"]
    expires_in_seconds: int = OTP_EXPIRY_SECONDS
    cooldown_seconds: int = 60
    debug_otp: str | None = None


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str
    purpose: Literal["signup", "signin"] = "signin"
    full_name: str | None = None
    account_type: Optional[Literal["candidate", "employer"]] = None

    @field_validator("purpose", mode="before")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("otp", mode="before")
    @classmethod
    def normalize_otp(cls, value: str) -> str:
        otp = str(value).strip()
        if len(otp) != 6 or not otp.isdigit():
            raise ValueError("OTP must be a 6-digit numeric code")
        return otp

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = str(value).strip()
        return trimmed or None


class OAuthProvidersResponse(BaseModel):
    google: bool
    linkedin: bool
    microsoft: bool


class AuthAuditEventResponse(BaseModel):
    id: str
    event_type: str
    email: Optional[str] = None
    account_type: Optional[str] = None
    purpose: Optional[str] = None
    success: bool
    reason: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    user_id: Optional[str] = None
    lock_applied: bool
    lock_until: Optional[str] = None
    created_at: str


class AuthAbuseLockResponse(BaseModel):
    key: str
    email: str
    action: str
    purpose: str
    failed_attempts: int
    lock_until: Optional[str] = None
    updated_at: str


async def _validate_user_for_purpose(email: str, purpose: Literal["signup", "signin"]) -> User | None:
    _reject_reserved_admin_identity_for_public_auth(email)
    user = await User.find_one(User.email == email)
    if purpose == "signin" and not user:
        raise HTTPException(
            status_code=404,
            detail="No account found for this email. Please sign up first.",
        )
    if purpose == "signup" and user:
        raise HTTPException(
            status_code=400,
            detail="An account already exists for this email. Please sign in.",
        )
    return user


@router.get("/oauth/providers", response_model=OAuthProvidersResponse)
async def oauth_providers() -> Any:
    """
    Surface which OAuth providers are currently configured server-side.
    """
    return OAuthProvidersResponse(
        google=_google_oauth_is_configured(),
        linkedin=bool((settings.LINKEDIN_OAUTH_CLIENT_ID or "").strip()),
        microsoft=bool((settings.MICROSOFT_OAUTH_CLIENT_ID or "").strip()),
    )


@router.get("/oauth/google/start", response_model=dict)
async def oauth_google_start(
    account_type: Literal["candidate", "employer"] = "candidate",
    next: Optional[str] = None,
    frontend_origin: Optional[str] = None,
) -> Any:
    """
    Returns Google OAuth authorization URL for the frontend to redirect users.
    """
    if not _google_oauth_is_configured():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    safe_account_type = _normalize_account_type(account_type)
    safe_next = _sanitize_next_path(next)
    redirect_uri = _resolve_google_redirect_uri(frontend_origin)
    state_payload: dict[str, Any] = {
        "account_type": safe_account_type,
        "next": safe_next,
        "nonce": secrets.token_urlsafe(12),
        "redirect_uri": redirect_uri,
    }
    safe_frontend_origin = _normalize_frontend_origin(frontend_origin)
    if safe_frontend_origin:
        state_payload["frontend_origin"] = safe_frontend_origin
    state = _base64url_encode(state_payload)

    query = urlencode(
        {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "include_granted_scopes": "true",
            "prompt": "select_account",
            "state": state,
        }
    )
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
    return {"redirect_url": auth_url}


@router.get("/oauth/google/callback")
async def oauth_google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    request: Request = None,  # type: ignore[assignment]
) -> Any:
    """
    Google OAuth callback: exchanges code, verifies ID token, and redirects to frontend with API JWT.
    """
    account_type = "candidate"
    next_path = "/dashboard"
    frontend_origin: Optional[str] = None
    redirect_uri = (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    ip_address, user_agent = _request_context(request)

    if state:
        try:
            state_payload = _base64url_decode(state)
            account_type = _normalize_account_type(state_payload.get("account_type"), default="candidate")
            next_path = _sanitize_next_path(state_payload.get("next"))
            frontend_origin = _normalize_frontend_origin(state_payload.get("frontend_origin"))
            candidate_redirect_uri = str(state_payload.get("redirect_uri") or "").strip()
            if _is_allowed_google_redirect_uri(candidate_redirect_uri):
                redirect_uri = candidate_redirect_uri
        except Exception:
            pass

    success_url, failure_url = _resolve_oauth_frontend_urls(frontend_origin)

    if error:
        await auth_security_service.audit_event(
            event_type="oauth.google",
            email=None,
            account_type=account_type,
            purpose="signin",
            success=False,
            reason=f"oauth_error:{str(error)}",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        target = _append_query(
            failure_url,
            {
                "error": "oauth_access_denied",
                "message": str(error),
            },
        )
        return RedirectResponse(target, status_code=302)

    if not code:
        await auth_security_service.audit_event(
            event_type="oauth.google",
            email=None,
            account_type=account_type,
            purpose="signin",
            success=False,
            reason="missing_code",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        target = _append_query(
            failure_url,
            {
                "error": "oauth_missing_code",
                "message": "Missing OAuth authorization code.",
            },
        )
        return RedirectResponse(target, status_code=302)

    if not _google_oauth_is_configured():
        await auth_security_service.audit_event(
            event_type="oauth.google",
            email=None,
            account_type=account_type,
            purpose="signin",
            success=False,
            reason="oauth_not_configured",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        target = _append_query(
            failure_url,
            {
                "error": "oauth_not_configured",
                "message": "Google OAuth is not configured.",
            },
        )
        return RedirectResponse(target, status_code=302)

    try:
        token_response = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        id_token_value = str(token_payload.get("id_token") or "").strip()
        if not id_token_value:
            raise ValueError("Google token exchange did not return id_token")

        try:
            from google.auth.transport import requests as google_transport_requests
            from google.oauth2 import id_token as google_id_token
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("google-auth package is required for OAuth verification") from exc

        id_info = google_id_token.verify_oauth2_token(
            id_token_value,
            google_transport_requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID,
        )
        issuer = str(id_info.get("iss") or "")
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Invalid Google token issuer")

        email = str(id_info.get("email") or "").strip().lower()
        if not email:
            raise ValueError("Google profile missing email")
        _reject_reserved_admin_identity_for_public_auth(email)

        email_verified = bool(id_info.get("email_verified"))
        if not email_verified:
            raise ValueError("Google email is not verified")

        full_name = str(id_info.get("name") or "").strip() or email.split("@")[0]

        if account_type == "employer":
            _ensure_employer_corporate_email(email)

        user = await User.find_one(User.email == email)
        if not user:
            user = User(
                email=email,
                full_name=full_name,
                hashed_password="OAUTH_GOOGLE_NO_PASSWORD",
                account_type=account_type,
                auth_provider="google",
                is_active=True,
            )
            await user.insert()
            await ensure_system_username(user)
        else:
            existing_account_type = _normalize_account_type(getattr(user, "account_type", "candidate"), default="candidate")
            if account_type != existing_account_type:
                raise ValueError(
                    f"This email is already registered as {existing_account_type}. "
                    f"Please continue as {existing_account_type}."
                )
            if existing_account_type == "employer":
                _ensure_employer_corporate_email(email)
            if not user.full_name:
                user.full_name = full_name
            if not user.account_type:
                user.account_type = account_type
            if not user.auth_provider:
                user.auth_provider = "google"
            await user.save()
            await ensure_system_username(user)

        if not user.is_active:
            raise ValueError("Inactive user account")

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        api_token = create_access_token(
            str(user.id),
            expires_delta=access_token_expires,
            scopes=_scopes_for_user(user),
        )
        await auth_security_service.audit_event(
            event_type="oauth.google",
            email=email,
            account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
            purpose="signin",
            success=True,
            reason="ok",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )

        success_query: dict[str, str] = {
            "token_type": "bearer",
            "provider": "google",
            "next": next_path,
        }
        if auth_cookie_only_mode_enabled():
            success_query["access_token"] = COOKIE_SESSION_SENTINEL
        # Keep URL token fallback only when cookie sessions are disabled and bearer compatibility remains enabled.
        elif not settings.AUTH_SESSION_COOKIE_ENABLED:
            success_query["access_token"] = api_token
        target = _append_query(success_url, success_query)
        redirect = RedirectResponse(target, status_code=302)
        _set_session_cookie(redirect, api_token)
        return redirect

    except Exception as exc:
        logger.exception("Google OAuth callback failed")
        await auth_security_service.audit_event(
            event_type="oauth.google",
            email=None,
            account_type=account_type,
            purpose="signin",
            success=False,
            reason=str(exc),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        target = _append_query(
            failure_url,
            {
                "error": "oauth_callback_failed",
                "message": str(exc),
            },
        )
        return RedirectResponse(target, status_code=302)


@router.post("/send-otp", response_model=OTPSendResponse)
async def send_otp(request: OTPSendRequest, http_request: Request = None):  # type: ignore[assignment]
    """
    Generate a 6-digit OTP, store in MongoDB, and dispatch email.
    """
    normalized_email = str(request.email).strip().lower()
    ip_address, user_agent = _request_context(http_request)
    existing_user = await _validate_user_for_purpose(normalized_email, request.purpose)
    requested_account_type = _normalize_account_type(request.account_type, default="candidate")

    if request.purpose == "signin":
        if not existing_user:
            raise HTTPException(status_code=404, detail="No account found for this email")
        existing_account_type = _normalize_account_type(
            getattr(existing_user, "account_type", "candidate"),
            default="candidate",
        )
        if request.account_type and requested_account_type != existing_account_type:
            raise HTTPException(
                status_code=400,
                detail=f"This email is registered as {existing_account_type}. Please continue as {existing_account_type}.",
            )
        if existing_account_type == "employer":
            _ensure_employer_corporate_email(normalized_email)
    else:
        if requested_account_type == "employer":
            _ensure_employer_corporate_email(normalized_email)

    cooldown_seconds = max(1, int(settings.OTP_SEND_COOLDOWN_SECONDS))
    remaining_cooldown = await get_otp_cooldown_remaining(
        normalized_email,
        purpose=request.purpose,
        cooldown_seconds=cooldown_seconds,
    )
    if remaining_cooldown > 0:
        await auth_security_service.audit_event(
            event_type="otp.send",
            email=normalized_email,
            account_type=requested_account_type,
            purpose=request.purpose,
            success=False,
            reason="cooldown_active",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=existing_user.id if existing_user else None,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {remaining_cooldown} seconds before requesting another OTP.",
            headers={"Retry-After": str(remaining_cooldown)},
        )

    otp = f"{secrets.randbelow(1_000_000):06d}"
    await set_otp(
        normalized_email,
        otp,
        expire_seconds=OTP_EXPIRY_SECONDS,
        purpose=request.purpose,
    )

    delivery: Literal["email", "debug"] = "email"
    debug_otp: str | None = None

    try:
        await send_email_otp(normalized_email, otp)
    except Exception as exc:
        environment = settings.ENVIRONMENT.strip().lower()
        if settings.OTP_ALLOW_DEBUG_FALLBACK and environment in LOCAL_ENV_NAMES:
            delivery = "debug"
            debug_otp = otp
            logger.warning(
                "OTP email delivery unavailable in %s environment; using debug fallback for %s: %s (%s)",
                environment,
                normalized_email,
                otp,
                exc,
            )
        else:
            logger.exception(
                "OTP email delivery failed in %s environment for %s",
                environment,
                normalized_email,
            )
            await delete_otp(normalized_email, purpose=request.purpose)
            await auth_security_service.audit_event(
                event_type="otp.send",
                email=normalized_email,
                account_type=requested_account_type,
                purpose=request.purpose,
                success=False,
                reason="delivery_failed",
                ip_address=ip_address,
                user_agent=user_agent,
                user_id=existing_user.id if existing_user else None,
            )
            raise HTTPException(
                status_code=502,
                detail="Unable to send OTP email. Please verify SMTP settings and try again.",
            )

    await auth_security_service.audit_event(
        event_type="otp.send",
        email=normalized_email,
        account_type=requested_account_type,
        purpose=request.purpose,
        success=True,
        reason="ok",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=existing_user.id if existing_user else None,
    )

    return OTPSendResponse(
        message=(
            "OTP sent successfully"
            if delivery == "email"
            else "OTP generated in local debug mode. Use the provided code to continue."
        ),
        delivery=delivery,
        cooldown_seconds=cooldown_seconds,
        debug_otp=debug_otp,
    )


@router.post("/verify-otp", response_model=Token)
async def verify_otp(
    request: OTPVerifyRequest,
    http_request: Request = None,  # type: ignore[assignment]
    response: Response = None,  # type: ignore[assignment]
) -> Any:
    """
    Verify the 6-digit OTP from MongoDB.
    For signup, creates an account after OTP success.
    For signin, requires an existing account.
    """
    normalized_email = str(request.email).strip().lower()
    ip_address, user_agent = _request_context(http_request)
    lock = await auth_security_service.check_lock(email=normalized_email, action="otp_verify", purpose=request.purpose)
    if lock.locked:
        await auth_security_service.audit_event(
            event_type="otp.verify",
            email=normalized_email,
            purpose=request.purpose,
            success=False,
            reason="account_locked",
            ip_address=ip_address,
            user_agent=user_agent,
            lock_applied=True,
            lock_until=lock.lock_until,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed OTP attempts. Try again in {lock.remaining_lock_seconds} seconds.",
            headers={"Retry-After": str(max(1, lock.remaining_lock_seconds))},
        )
    user = await _validate_user_for_purpose(normalized_email, request.purpose)

    if request.purpose == "signup":
        signup_account_type = _normalize_account_type(request.account_type, default="candidate")
        if signup_account_type == "employer":
            _ensure_employer_corporate_email(normalized_email)
    else:
        if not user:
            raise HTTPException(status_code=404, detail="No account found for this email")
        existing_account_type = _normalize_account_type(
            getattr(user, "account_type", "candidate"),
            default="candidate",
        )
        requested_account_type = _normalize_account_type(request.account_type, default=existing_account_type)
        if request.account_type and requested_account_type != existing_account_type:
            raise HTTPException(
                status_code=400,
                detail=f"This email is registered as {existing_account_type}. Please continue as {existing_account_type}.",
            )
        if existing_account_type == "employer":
            _ensure_employer_corporate_email(normalized_email)

    is_valid = await validate_otp(
        normalized_email,
        request.otp,
        purpose=request.purpose,
    )
    if not is_valid:
        failure = await auth_security_service.record_failure(
            email=normalized_email,
            action="otp_verify",
            purpose=request.purpose,
        )
        await auth_security_service.audit_event(
            event_type="otp.verify",
            email=normalized_email,
            account_type=_normalize_account_type(request.account_type, default="candidate")
            if request.purpose == "signup"
            else _normalize_account_type(getattr(user, "account_type", "candidate"), default="candidate")
            if user
            else None,
            purpose=request.purpose,
            success=False,
            reason="invalid_or_expired_otp",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id if user else None,
            lock_applied=failure.locked,
            lock_until=failure.lock_until,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    await delete_otp(normalized_email, purpose=request.purpose)

    if request.purpose == "signup":
        account_type = _normalize_account_type(request.account_type, default="candidate")
        user = User(
            email=normalized_email,
            full_name=request.full_name or str(request.email).split("@")[0],
            hashed_password="OTP_NO_PASSWORD",
            is_active=True,
            account_type=account_type,
            auth_provider="otp",
        )
        await user.insert()
        await ensure_system_username(user)

    if not user:
        raise HTTPException(status_code=404, detail="No account found for this email")

    if not (user.username or "").strip():
        await ensure_system_username(user)

    if not user.is_active:
        await auth_security_service.audit_event(
            event_type="otp.verify",
            email=normalized_email,
            account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
            purpose=request.purpose,
            success=False,
            reason="inactive_user",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=user.id,
        )
        raise HTTPException(status_code=400, detail="Inactive user account")

    await auth_security_service.record_success(email=normalized_email, action="otp_verify", purpose=request.purpose)
    await auth_security_service.audit_event(
        event_type="otp.verify",
        email=normalized_email,
        account_type=str(getattr(user, "account_type", "candidate") or "candidate"),
        purpose=request.purpose,
        success=True,
        reason="ok",
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=user.id,
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        str(user.id),
        expires_delta=access_token_expires,
        scopes=_scopes_for_user(user),
    )
    _set_session_cookie(response, token)
    return _token_response_payload(token)


@router.post("/logout", response_model=dict)
async def logout(response: Response) -> Any:
    _clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/audit-events", response_model=list[AuthAuditEventResponse])
async def list_auth_audit_events(
    event_type: Optional[str] = None,
    email: Optional[str] = None,
    purpose: Optional[str] = None,
    success: Optional[bool] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters: list[Any] = []
    if event_type:
        query_filters.append(AuthAuditEvent.event_type == event_type.strip().lower())
    if email:
        query_filters.append(AuthAuditEvent.email == email.strip().lower())
    if purpose:
        query_filters.append(AuthAuditEvent.purpose == purpose.strip().lower())
    if success is not None:
        query_filters.append(AuthAuditEvent.success == bool(success))

    rows = await AuthAuditEvent.find_many(*query_filters).sort("-created_at").limit(limit).to_list()
    return [
        AuthAuditEventResponse(
            id=str(row.id),
            event_type=row.event_type,
            email=row.email,
            account_type=row.account_type,
            purpose=row.purpose,
            success=bool(row.success),
            reason=row.reason,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            user_id=str(row.user_id) if row.user_id else None,
            lock_applied=bool(row.lock_applied),
            lock_until=row.lock_until.isoformat() if row.lock_until else None,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/abuse-locks", response_model=list[AuthAbuseLockResponse])
async def list_auth_abuse_locks(
    email: Optional[str] = None,
    action: Optional[str] = None,
    only_locked: bool = True,
    limit: int = Query(default=200, ge=1, le=2000),
    _: User = Depends(get_current_admin_user),
) -> Any:
    query_filters: list[Any] = []
    if email:
        query_filters.append(AuthAbuseState.email == email.strip().lower())
    if action:
        query_filters.append(AuthAbuseState.action == action.strip().lower())

    rows = await AuthAbuseState.find_many(*query_filters).sort("-updated_at").limit(limit).to_list()
    if only_locked:
        now = utc_now()
        rows = [row for row in rows if row.lock_until is not None and row.lock_until > now]

    return [
        AuthAbuseLockResponse(
            key=row.key,
            email=row.email,
            action=row.action,
            purpose=row.purpose,
            failed_attempts=int(row.failed_attempts),
            lock_until=row.lock_until.isoformat() if row.lock_until else None,
            updated_at=row.updated_at.isoformat(),
        )
        for row in rows
    ]
