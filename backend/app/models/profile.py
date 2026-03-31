from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field

class Profile(Document):
    user_id: PydanticObjectId = Field(unique=True)
    bio: Optional[str] = None
    skills: Optional[str] = None
    interests: Optional[str] = None
    achievements: Optional[str] = None
    education: Optional[str] = None
    resume_url: Optional[str] = None
    incoscore: float = 0.0

    class Settings:
        name = "profiles"
        indexes = ["user_id"]
