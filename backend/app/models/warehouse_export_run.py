from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from beanie import Document
from pydantic import Field

from app.core.time import utc_now


class WarehouseExportRun(Document):
    traffic_type: str = Field(default="real")
    export_format: str = Field(default="duckdb_parquet")
    lookback_days: int = Field(default=30, ge=1, le=365)
    status: str = Field(default="ok")
    exported_tables: list[str] = Field(default_factory=list)
    raw_files: dict[str, str] = Field(default_factory=dict)
    mart_files: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    class Settings:
        name = "warehouse_export_runs"
        indexes = [
            "traffic_type",
            "export_format",
            "status",
            "created_at",
        ]
