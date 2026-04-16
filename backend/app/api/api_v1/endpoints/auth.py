from __future__ import annotations

from datetime import timedelta
import logging
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter()

@router.post("/register", response_model=UserResponse)
async def register_user(
    user_in: UserCreate
) -> Any:
    """
    Create new user.
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
    )
    await user.insert()
    return user

@router.post("/login", response_model=Token)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = await User.find_one(User.email == form_data.username)
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            str(user.id), expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

from pydantic import BaseModel, EmailStr, field_validator
from app.core.redis_client import set_otp, validate_otp, delete_otp
from app.services.email import send_email_otp

OTP_EXPIRY_SECONDS = 300
LOCAL_ENV_NAMES = {"local", "dev", "development", "test"}
logger = logging.getLogger(__name__)

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
    full_name: str | None = None  # Optional, provided during sign-up to set the user's name

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
        value = str(value).strip()
        return value or None


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

    # Valid OTP, consume it so it cannot be reused.
    await delete_otp(normalized_email, purpose=request.purpose)

    if request.purpose == "signup":
        user = User(
            email=normalized_email,
            full_name=request.full_name or str(request.email).split("@")[0],
            hashed_password="OAUTH_OTP_NO_PASSWORD",  # Placeholder for OTP-only accounts
            is_active=True,
        )
        await user.insert()

    if not user:
        raise HTTPException(status_code=404, detail="No account found for this email")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user account")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": create_access_token(
            str(user.id), expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }
