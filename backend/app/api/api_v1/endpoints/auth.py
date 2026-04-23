from __future__ import annotations

import base64
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.core.email_policy import is_corporate_email
from app.core.redis_client import delete_otp, get_otp_cooldown_remaining, set_otp, validate_otp
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.auth_abuse_state import AuthAbuseState
from app.models.auth_audit_event import AuthAuditEvent
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse
from app.services.auth_security_service import auth_security_service
from app.services.email import send_email_otp

router = APIRouter()
logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 300
LOCAL_ENV_NAMES = {"local", "dev", "development", "test"}
VALID_ACCOUNT_TYPES = {"candidate", "employer"}
LOCAL_OAUTH_HOSTS = {"localhost", "127.0.0.1"}


def _scopes_for_user(user: User) -> list[str]:
    scopes = ["user"]
    if bool(getattr(user, "is_admin", False)):
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


@router.post("/register", response_model=UserResponse)
async def register_user(
    user_in: UserCreate
) -> Any:
    """
    Create new user via password flow.
    """
    user = await User.find_one(User.email == user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        account_type="candidate",
        auth_provider="password",
    )
    await user.insert()
    return user


@router.post("/login", response_model=Token)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,  # type: ignore[assignment]
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
    return {
        "access_token": create_access_token(
            str(user.id),
            expires_delta=access_token_expires,
            scopes=_scopes_for_user(user),
        ),
        "token_type": "bearer",
    }


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

        target = _append_query(
            success_url,
            {
                "access_token": api_token,
                "token_type": "bearer",
                "provider": "google",
                "next": next_path,
            },
        )
        return RedirectResponse(target, status_code=302)

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

    if not user:
        raise HTTPException(status_code=404, detail="No account found for this email")

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
    return {
        "access_token": create_access_token(
            str(user.id),
            expires_delta=access_token_expires,
            scopes=_scopes_for_user(user),
        ),
        "token_type": "bearer",
    }


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
        now = datetime.utcnow()
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
