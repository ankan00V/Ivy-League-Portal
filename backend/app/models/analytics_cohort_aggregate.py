from __future__ import annotations

from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AnalyticsCohortAggregate(Document):
    cohort_date: str = Field(index=True, min_length=10, max_length=10)
    days_since_cohort: int = Field(index=True, ge=0)
    traffic_type: str = Field(default="real", index=True)
    users_in_cohort: int = Field(default=0, ge=0)
    active_users: int = Field(default=0, ge=0)
    applying_users: int = Field(default=0, ge=0)
    retention_rate: float = Field(default=0.0, ge=0.0)
    apply_rate: float = Field(default=0.0, ge=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "analytics_cohort_aggregates"
        indexes = [
            IndexModel(
                [("cohort_date", 1), ("days_since_cohort", 1), ("traffic_type", 1)],
                unique=True,
            ),
            "cohort_date",
            "days_since_cohort",
            "traffic_type",
            "updated_at",
        ]
