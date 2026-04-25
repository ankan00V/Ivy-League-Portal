from typing import Optional
from datetime import datetime
from beanie import Document
from pydantic import Field

class User(Document):
    email: str = Field(unique=True)
    hashed_password: str
    full_name: Optional[str] = None
    username: Optional[str] = None
    account_type: str = "candidate"  # candidate | employer
    auth_provider: str = "otp"  # otp | google | linkedin | microsoft | password
    is_active: bool = True
    is_admin: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = ["email", "username", "full_name", "account_type", "auth_provider"]
