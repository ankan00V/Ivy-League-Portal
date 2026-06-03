import ipaddress

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from beanie import PydanticObjectId

from app.core.config import auth_cookie_only_mode_enabled, settings
from app.core.email_policy import is_corporate_email
from app.models.user import User
from app.schemas.user import TokenData
from app.services.admin_identity_service import is_reserved_admin_email
from app.services.auth_security_service import auth_security_service
from app.services.session_security_service import session_security_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)


def _token_from_request_cookie(request: Request) -> str | None:
    if not settings.AUTH_SESSION_COOKIE_ENABLED:
        return None
    cookie_name = (settings.AUTH_SESSION_COOKIE_NAME or "").strip()
    if not cookie_name:
        return None
    token = request.cookies.get(cookie_name)
    if not token:
        return None
    return str(token).strip() or None


def _looks_like_jwt(value: str | None) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    return candidate.count(".") == 2


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    header_token = (token or "").strip() or None
    cookie_token = _token_from_request_cookie(request)
    candidate_tokens: list[str] = []

    cookie_only_mode = auth_cookie_only_mode_enabled()

    # Ignore malformed bearer tokens. In cookie-only mode, headers are never trusted.
    if not cookie_only_mode and _looks_like_jwt(header_token):
        candidate_tokens.append(str(header_token))
    if _looks_like_jwt(cookie_token):
        candidate_tokens.append(str(cookie_token))

    if not candidate_tokens:
        raise credentials_exception

    token_data: TokenData | None = None
    for candidate in candidate_tokens:
        try:
            payload = jwt.decode(
                candidate, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            user_id: str = payload.get("sub")
            if user_id is None:
                continue
            raw_scopes = payload.get("scopes") or []
            if isinstance(raw_scopes, str):
                scopes = [raw_scopes]
            elif isinstance(raw_scopes, list):
                scopes = [str(scope) for scope in raw_scopes if scope]
            else:
                scopes = []
            token_data = TokenData(id=user_id, scopes=scopes, session_id=str(payload.get("jti") or "").strip() or None)
            break
        except JWTError:
            continue

    if token_data is None:
        raise credentials_exception
        
    try:
        user = await User.get(PydanticObjectId(token_data.id))
    except Exception:
        raise credentials_exception
    
    if user is None:
        raise credentials_exception
    session_decision = await session_security_service.validate_session(
        user=user,
        session_id=token_data.session_id,
        request=request,
    )
    if not session_decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Attach token scopes for downstream dependencies.
    setattr(user, "_token_scopes", list(token_data.scopes or []))
    setattr(user, "_token_session_id", token_data.session_id)
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def _admin_ip_allowed(ip_address: str) -> bool:
    configured = list(settings.ADMIN_ALLOWED_IPS or [])
    if not configured:
        return True
    try:
        client_ip = ipaddress.ip_address(ip_address)
    except Exception:
        return False
    for entry in configured:
        candidate = str(entry or "").strip()
        if not candidate:
            continue
        try:
            if "/" in candidate:
                if client_ip in ipaddress.ip_network(candidate, strict=False):
                    return True
            elif client_ip == ipaddress.ip_address(candidate):
                return True
        except Exception:
            continue
    return False


async def get_current_admin_user(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent")
    scopes = set(getattr(current_user, "_token_scopes", []) or [])
    authorized = "admin" in scopes or bool(current_user.is_admin)
    reserved_identity = is_reserved_admin_email(getattr(current_user, "email", ""))
    allowlisted = _admin_ip_allowed(ip_address)
    if not authorized or not reserved_identity:
        await auth_security_service.audit_event(
            event_type="admin.access_denied",
            email=getattr(current_user, "email", None),
            account_type=getattr(current_user, "account_type", None),
            purpose="admin",
            success=False,
            reason="not_enough_privileges",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=current_user.id,
        )
        raise HTTPException(status_code=403, detail="Not enough privileges")
    if not allowlisted:
        await auth_security_service.audit_event(
            event_type="admin.access_denied",
            email=getattr(current_user, "email", None),
            account_type=getattr(current_user, "account_type", None),
            purpose="admin",
            success=False,
            reason="ip_not_allowed",
            ip_address=ip_address,
            user_agent=user_agent,
            user_id=current_user.id,
        )
        raise HTTPException(status_code=403, detail="Admin IP is not allowed")
    await auth_security_service.audit_event(
        event_type="admin.api_call",
        email=getattr(current_user, "email", None),
        account_type=getattr(current_user, "account_type", None),
        purpose="admin",
        success=True,
        reason=request.url.path,
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=current_user.id,
    )
    return current_user


async def get_current_employer_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if not current_user.is_admin and str(getattr(current_user, "account_type", "candidate")).strip().lower() != "employer":
        raise HTTPException(status_code=403, detail="Employer account required")
    if (
        not current_user.is_admin
        and str(getattr(current_user, "account_type", "candidate")).strip().lower() == "employer"
        and not is_corporate_email(getattr(current_user, "email", ""))
    ):
        raise HTTPException(status_code=403, detail="Employer access requires a corporate email")
    return current_user


def require_scopes(required: list[str]):
    required_set = {str(scope) for scope in required if scope}

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        scopes = set(getattr(current_user, "_token_scopes", []) or [])
        missing = [scope for scope in required_set if scope not in scopes]
        if missing:
            raise HTTPException(status_code=403, detail="Missing required scopes")
        return current_user

    return _dependency
