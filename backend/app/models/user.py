from typing import Optional
from datetime import datetime
from app.core.time import utc_now
from beanie import Document
from pydantic import Field

class User(Document):
    email: str = Field(json_schema_extra={"unique": True})
    hashed_password: str
    full_name: Optional[str] = None
    username: Optional[str] = None
    account_type: str = "candidate"  # candidate | employer
    auth_provider: str = "otp"  # otp | google | linkedin | microsoft | password
    is_active: bool = True
    is_admin: bool = False
    totp_enabled: bool = False
    totp_secret_encrypted: Optional[str] = None
    profile_embedding: list[float] = Field(default_factory=list)
    profile_embedding_model_version: Optional[str] = Field(default=None, json_schema_extra={"index": True})
    profile_embedding_updated_at: Optional[datetime] = Field(default=None, json_schema_extra={"index": True})
    profile_embedding_interaction_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "users"
        indexes = [
            "email",
            "username",
            "full_name",
            "account_type",
            "auth_provider",
            "profile_embedding_model_version",
            "profile_embedding_updated_at",
        ]

    @property
    def needs_password_setup(self) -> bool:
        hashed = str(self.hashed_password or "").strip()
        return not hashed or hashed in {"OTP_NO_PASSWORD", "OAUTH_GOOGLE_NO_PASSWORD"} or hashed.endswith("_NO_PASSWORD")
