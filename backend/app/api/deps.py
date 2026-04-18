from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from beanie import PydanticObjectId

from app.core.config import settings
from app.core.email_policy import is_corporate_email
from app.models.user import User
from app.schemas.user import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        raw_scopes = payload.get("scopes") or []
        if isinstance(raw_scopes, str):
            scopes = [raw_scopes]
        elif isinstance(raw_scopes, list):
            scopes = [str(scope) for scope in raw_scopes if scope]
        else:
            scopes = []
        token_data = TokenData(id=user_id, scopes=scopes)
    except JWTError:
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
