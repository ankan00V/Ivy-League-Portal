from __future__ import annotations

from datetime import datetime
from app.core.time import utc_now
from typing import Literal, Optional
from uuid import uuid4

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel


class ExperimentVariant(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0.0)
    is_control: bool = False


ExperimentStatus = Literal["active", "paused", "archived"]


class Experiment(Document):
    key: Indexed(str, unique=True)  # type: ignore[valid-type]
    description: Optional[str] = None
    status: ExperimentStatus = "active"
    variants: list[ExperimentVariant] = Field(default_factory=list)
    # Salt can be rotated to re-randomize future assignments; existing users remain sticky via assignments collection.
    salt: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "experiments"
        indexes = [
            "key",
            "status",
            "updated_at",
        ]


class ExperimentAssignment(Document):
    user_id: PydanticObjectId = Field(json_schema_extra={"index": True})
    experiment_key: str = Field(json_schema_extra={"index": True})
    variant: str
    bucket: int = Field(ge=0, le=9999)
    assigned_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "experiment_assignments"
        indexes = [
            IndexModel([("user_id", 1), ("experiment_key", 1)], unique=True),
            "experiment_key",
            "variant",
            "assigned_at",
        ]

