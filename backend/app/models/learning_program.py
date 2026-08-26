"""Industry-published learning programmes.

The problem statement asks companies to publish "training programs, certification
courses, workshops, and mentorship initiatives to help students acquire in-demand
skills before applying". The value is not the listing, which any noticeboard
does; it is that a programme names the skills it teaches, so it can be matched
against the gaps the assessment already found. Assessment -> gap -> a programme
that closes it is the loop the statement describes, and skills_taught is the only
thing that makes the last step possible.

Publication is gated the same way employer listings are: a programme is a claim
about training that students will spend weeks on, and an unverified account
should not be able to put one in front of them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.time import utc_now

PROGRAM_FORMATS = ("course", "certification", "workshop", "mentorship", "bootcamp")
PROGRAM_MODES = ("online", "offline", "hybrid")
PROGRAM_STATUSES = ("draft", "published", "closed")


class LearningProgram(Document):
    title: str = Field(min_length=3, max_length=220)
    description: str = Field(min_length=20, max_length=8000)
    provider: str = Field(min_length=2, max_length=200)
    url: Optional[str] = Field(default=None, max_length=1200)

    program_format: str = Field(default="course", json_schema_extra={"index": True})
    delivery_mode: str = Field(default="online")
    duration_weeks: Optional[int] = Field(default=None, ge=0, le=520)
    is_free: bool = True
    cost_inr: Optional[int] = Field(default=None, ge=0)
    certificate_offered: bool = False

    #: The skills this programme claims to teach, normalised. Without these a
    #: programme cannot be matched to a gap and is just an advert.
    skills_taught: list[str] = Field(default_factory=list)

    posted_by_user_id: Optional[PydanticObjectId] = Field(default=None, json_schema_extra={"index": True})
    status: str = Field(default="draft", json_schema_extra={"index": True})
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("skills_taught")
    @classmethod
    def clean_skills(cls, value: list[str]) -> list[str]:
        # Matching is by exact skill name against the demand table, so casing and
        # duplicates here silently reduce how many gaps a programme can close.
        seen: dict[str, None] = {}
        for item in value or []:
            cleaned = " ".join(str(item or "").split()).lower()
            if cleaned:
                seen.setdefault(cleaned, None)
        return list(seen)[:40]

    @field_validator("program_format")
    @classmethod
    def valid_format(cls, value: str) -> str:
        cleaned = str(value or "course").strip().lower()
        if cleaned not in PROGRAM_FORMATS:
            raise ValueError(f"program_format must be one of: {', '.join(PROGRAM_FORMATS)}")
        return cleaned

    @field_validator("delivery_mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        cleaned = str(value or "online").strip().lower()
        if cleaned not in PROGRAM_MODES:
            raise ValueError(f"delivery_mode must be one of: {', '.join(PROGRAM_MODES)}")
        return cleaned

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        cleaned = str(value or "draft").strip().lower()
        if cleaned not in PROGRAM_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(PROGRAM_STATUSES)}")
        return cleaned

    class Settings:
        name = "learning_programs"
        indexes = [
            IndexModel([("status", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("posted_by_user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
