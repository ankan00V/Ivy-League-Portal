from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document
from pydantic import Field

from app.core.time import utc_now


ScraperRunStatus = Literal["success", "partial", "failed"]


class ScraperRunLog(Document):
    source_name: str = Field(json_schema_extra={"index": True})
    run_start: datetime = Field(json_schema_extra={"index": True})
    run_end: datetime = Field(json_schema_extra={"index": True})
    status: ScraperRunStatus = Field(json_schema_extra={"index": True})

    items_fetched: int = Field(default=0, ge=0)
    items_parsed: int = Field(default=0, ge=0)
    items_inserted: int = Field(default=0, ge=0)
    items_updated: int = Field(default=0, ge=0)
    items_deduplicated: int = Field(default=0, ge=0)
    parse_error_count: int = Field(default=0, ge=0)
    error_samples: list[dict[str, Any]] = Field(default_factory=list)

    p50_parse_time_ms: Optional[float] = None
    p95_parse_time_ms: Optional[float] = None
    avg_trust_score: Optional[float] = None
    silent_failure: bool = Field(default=False, json_schema_extra={"index": True})

    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "scraper_run_logs"
        indexes = [
            "source_name",
            "status",
            "silent_failure",
            "run_start",
            "run_end",
            "created_at",
            [("source_name", 1), ("run_end", -1)],
            [("source_name", 1), ("status", 1), ("run_end", -1)],
        ]
