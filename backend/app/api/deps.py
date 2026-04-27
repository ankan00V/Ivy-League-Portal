from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from beanie import PydanticObjectId

from app.core.config import auth_cookie_only_mode_enabled, settings
from app.core.email_policy import is_corporate_email
from app.models.user import User
from app.schemas.user import TokenData
from app.services.admin_identity_service import is_reserved_admin_email

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
            token_data = TokenData(id=user_id, scopes=scopes)
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
    # Attach token scopes for downstream dependencies.
    setattr(user, "_token_scopes", list(token_data.scopes or []))
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    scopes = set(getattr(current_user, "_token_scopes", []) or [])
    if "admin" not in scopes and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough privileges")
    if not is_reserved_admin_email(getattr(current_user, "email", "")):
        raise HTTPException(status_code=403, detail="Not enough privileges")
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
