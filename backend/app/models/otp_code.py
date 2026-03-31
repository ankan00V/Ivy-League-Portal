from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class OTPCode(Document):
    email: str
    purpose: str = "signin"
    otp_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "otp_codes"
        indexes = [
            IndexModel([("email", 1), ("purpose", 1)], unique=True),
            IndexModel([("expires_at", 1)], expireAfterSeconds=0),
            "email",
        ]
