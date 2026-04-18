from __future__ import annotations

import base64
import json
import logging
import secrets
from datetime import timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, field_validator

from app.core.config import settings
from app.core.redis_client import delete_otp, set_otp, validate_otp
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse
from app.services.email import send_email_otp

router = APIRouter()
logger = logging.getLogger(__name__)

OTP_EXPIRY_SECONDS = 300
LOCAL_ENV_NAMES = {"local", "dev", "development", "test"}
VALID_ACCOUNT_TYPES = {"candidate", "employer"}


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


def _google_oauth_is_configured() -> bool:
    return bool(
        (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
        and (settings.GOOGLE_OAUTH_CLIENT_SECRET or "").strip()
        and (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    )


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
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    user = await User.find_one(User.email == form_data.username)

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

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

    @field_validator("purpose", mode="before")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        return str(value).strip().lower()


class OTPSendResponse(BaseModel):
    message: str
    delivery: Literal["email", "debug"]
    expires_in_seconds: int = OTP_EXPIRY_SECONDS
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
) -> Any:
    """
    Returns Google OAuth authorization URL for the frontend to redirect users.
    """
    if not _google_oauth_is_configured():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    safe_account_type = _normalize_account_type(account_type)
    safe_next = _sanitize_next_path(next)
    state = _base64url_encode(
        {
            "account_type": safe_account_type,
            "next": safe_next,
            "nonce": secrets.token_urlsafe(12),
        }
    )

    query = urlencode(
        {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
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
) -> Any:
    """
    Google OAuth callback: exchanges code, verifies ID token, and redirects to frontend with API JWT.
    """
    failure_url = settings.FRONTEND_OAUTH_FAILURE_URL
    success_url = settings.FRONTEND_OAUTH_SUCCESS_URL
    account_type = "candidate"
    next_path = "/dashboard"

    if state:
        try:
            state_payload = _base64url_decode(state)
            account_type = _normalize_account_type(state_payload.get("account_type"), default="candidate")
            next_path = _sanitize_next_path(state_payload.get("next"))
        except Exception:
            pass

    if error:
        target = _append_query(
            failure_url,
            {
                "error": "oauth_access_denied",
                "message": str(error),
            },
        )
        return RedirectResponse(target, status_code=302)

    if not code:
        target = _append_query(
            failure_url,
            {
                "error": "oauth_missing_code",
                "message": "Missing OAuth authorization code.",
            },
        )
        return RedirectResponse(target, status_code=302)

    if not _google_oauth_is_configured():
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
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
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
        target = _append_query(
            failure_url,
            {
                "error": "oauth_callback_failed",
                "message": str(exc),
            },
        )
        return RedirectResponse(target, status_code=302)


@router.post("/send-otp", response_model=OTPSendResponse)
async def send_otp(request: OTPSendRequest):
    """
    Generate a 6-digit OTP, store in MongoDB, and dispatch email.
    """
    normalized_email = str(request.email).strip().lower()
    await _validate_user_for_purpose(normalized_email, request.purpose)

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
            raise HTTPException(
                status_code=502,
                detail="Unable to send OTP email. Please verify SMTP settings and try again.",
            )

    return OTPSendResponse(
        message=(
            "OTP sent successfully"
            if delivery == "email"
            else "OTP generated in local debug mode. Use the provided code to continue."
        ),
        delivery=delivery,
        debug_otp=debug_otp,
    )


@router.post("/verify-otp", response_model=Token)
async def verify_otp(
    request: OTPVerifyRequest
) -> Any:
    """
    Verify the 6-digit OTP from MongoDB.
    For signup, creates an account after OTP success.
    For signin, requires an existing account.
    """
    normalized_email = str(request.email).strip().lower()
    user = await _validate_user_for_purpose(normalized_email, request.purpose)

    is_valid = await validate_otp(
        normalized_email,
        request.otp,
        purpose=request.purpose,
    )
    if not is_valid:
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
        raise HTTPException(status_code=400, detail="Inactive user account")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            str(user.id),
            expires_delta=access_token_expires,
            scopes=_scopes_for_user(user),
        ),
        "token_type": "bearer",
    }
