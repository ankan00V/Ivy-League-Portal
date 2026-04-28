from typing import Optional
from datetime import datetime
from app.core.time import utc_now
from beanie import Document, PydanticObjectId
from pydantic import Field

class Post(Document):
    user_id: PydanticObjectId
    domain: str
    content: str
    likes_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "posts"
        indexes = ["domain", "user_id"]

class Comment(Document):
    post_id: PydanticObjectId
    user_id: PydanticObjectId
    content: str
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "comments"
        indexes = ["post_id", "user_id"]
