from datetime import datetime
from app.core.time import utc_now

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class OTPCode(Document):
    email: str
    purpose: str = "signin"
    otp_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "otp_codes"
        indexes = [
            IndexModel([("email", 1), ("purpose", 1)], unique=True),
            IndexModel([("expires_at", 1)], expireAfterSeconds=0),
            "email",
        ]
