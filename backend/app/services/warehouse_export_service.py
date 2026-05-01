from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.metrics import WAREHOUSE_EXPORTS_TOTAL
from app.core.time import utc_now
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.warehouse_export_run import WarehouseExportRun


class WarehouseExportService:
    RAW_TABLE_SCHEMAS: dict[str, dict[str, str]] = {
        "opportunity_interactions": {
            "user_id": "VARCHAR",
            "opportunity_id": "VARCHAR",
            "interaction_type": "VARCHAR",
            "ranking_mode": "VARCHAR",
            "experiment_key": "VARCHAR",
            "experiment_variant": "VARCHAR",
            "model_version_id": "VARCHAR",
            "rank_position": "INTEGER",
            "match_score": "DOUBLE",
            "traffic_type": "VARCHAR",
            "created_at": "TIMESTAMP",
        },
        "ranking_request_telemetry": {
            "user_id": "VARCHAR",
            "request_kind": "VARCHAR",
            "ranking_mode": "VARCHAR",
            "experiment_key": "VARCHAR",
            "experiment_variant": "VARCHAR",
            "surface": "VARCHAR",
            "success": "BOOLEAN",
            "latency_ms": "DOUBLE",
            "results_count": "INTEGER",
            "traffic_type": "VARCHAR",
            "created_at": "TIMESTAMP",
        },
        "feature_store_rows": {
            "row_key": "VARCHAR",
            "date": "VARCHAR",
            "user_id": "VARCHAR",
            "opportunity_id": "VARCHAR",
            "ranking_mode": "VARCHAR",
            "experiment_key": "VARCHAR",
            "experiment_variant": "VARCHAR",
            "traffic_type": "VARCHAR",
            "rank_position": "INTEGER",
            "match_score": "DOUBLE",
            "features": "JSON",
            "labels": "JSON",
            "source_event_id": "VARCHAR",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
        },
        "analytics_daily": {
            "date": "VARCHAR",
            "metric_type": "VARCHAR",
            "traffic_type": "VARCHAR",
            "ranking_mode": "VARCHAR",
            "experiment_key": "VARCHAR",
            "experiment_variant": "VARCHAR",
            "request_kind": "VARCHAR",
            "metrics": "JSON",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
        },
        "analytics_funnels": {
            "date": "VARCHAR",
            "traffic_type": "VARCHAR",
            "ranking_mode": "VARCHAR",
            "experiment_key": "VARCHAR",
            "experiment_variant": "VARCHAR",
            "stage_counts": "JSON",
            "rates": "JSON",
            "metadata": "JSON",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
        },
        "analytics_cohorts": {
            "cohort_date": "VARCHAR",
            "days_since_cohort": "INTEGER",
            "traffic_type": "VARCHAR",
            "users_in_cohort": "INTEGER",
            "active_users": "INTEGER",
            "applying_users": "INTEGER",
            "retention_rate": "DOUBLE",
            "apply_rate": "DOUBLE",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
        },
    }

    def _enabled(self) -> bool:
        export_format = str(settings.ANALYTICS_WAREHOUSE_EXPORT_FORMAT or "").strip().lower()
        return bool(settings.ANALYTICS_WAREHOUSE_EXPORT_ENABLED) and export_format not in {"", "disabled"}

    def _safe_root(self) -> Path:
        return Path(settings.ANALYTICS_WAREHOUSE_EXPORT_ROOT).resolve()

    def _models_dir(self) -> Path:
        return Path(settings.ANALYTICS_WAREHOUSE_SQL_MODELS_DIR).resolve()

    def _render_sql(self, template: str, *, table_name: str, traffic_type: str, lookback_days: int) -> str:
        return (
            template.replace("{{ table_name }}", table_name)
            .replace("{{ traffic_type }}", traffic_type)
            .replace("{{ lookback_days }}", str(int(lookback_days)))
        )

    async def export(self, *, lookback_days: int, traffic_type: str) -> dict[str, Any]:
        if not self._enabled():
            return {"status": "disabled"}

        export_format = str(settings.ANALYTICS_WAREHOUSE_EXPORT_FORMAT or "duckdb_parquet").strip().lower()
        root = self._safe_root()
        root.mkdir(parents=True, exist_ok=True)
        raw_root = root / "raw"
        marts_root = root / "marts"
        raw_root.mkdir(parents=True, exist_ok=True)
        marts_root.mkdir(parents=True, exist_ok=True)

        try:
            interactions = [row.model_dump(mode="json") for row in await OpportunityInteraction.find_many(
                OpportunityInteraction.traffic_type == traffic_type
            ).to_list()]
            telemetry = [row.model_dump(mode="json") for row in await RankingRequestTelemetry.find_many(
                RankingRequestTelemetry.traffic_type == traffic_type
            ).to_list()]
            feature_rows = [row.model_dump(mode="json") for row in await FeatureStoreRow.find_many(
                FeatureStoreRow.traffic_type == traffic_type
            ).to_list()]
            daily = [row.model_dump(mode="json") for row in await AnalyticsDailyAggregate.find_many(
                AnalyticsDailyAggregate.traffic_type == traffic_type
            ).to_list()]
            funnels = [row.model_dump(mode="json") for row in await AnalyticsFunnelAggregate.find_many(
                AnalyticsFunnelAggregate.traffic_type == traffic_type
            ).to_list()]
            cohorts = [row.model_dump(mode="json") for row in await AnalyticsCohortAggregate.find_many(
                AnalyticsCohortAggregate.traffic_type == traffic_type
            ).to_list()]

            raw_files = {
                "opportunity_interactions": self._write_jsonl(raw_root / "opportunity_interactions.jsonl", interactions),
                "ranking_request_telemetry": self._write_jsonl(raw_root / "ranking_request_telemetry.jsonl", telemetry),
                "feature_store_rows": self._write_jsonl(raw_root / "feature_store_rows.jsonl", feature_rows),
                "analytics_daily": self._write_jsonl(raw_root / "analytics_daily.jsonl", daily),
                "analytics_funnels": self._write_jsonl(raw_root / "analytics_funnels.jsonl", funnels),
                "analytics_cohorts": self._write_jsonl(raw_root / "analytics_cohorts.jsonl", cohorts),
            }

            duckdb_path = None
            exported_tables: list[str] = []
            mart_files: dict[str, str] = {}
            if export_format in {"duckdb", "duckdb_parquet", "parquet"}:
                duckdb_path, exported_tables, mart_files = self._materialize_duckdb(
                    raw_files=raw_files,
                    marts_root=marts_root,
                    traffic_type=traffic_type,
                    lookback_days=lookback_days,
                    export_parquet=export_format in {"duckdb_parquet", "parquet"},
                )

            clickhouse_tables: list[str] = []
            if settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED and duckdb_path:
                clickhouse_tables = self._materialize_clickhouse(
                    duckdb_path=duckdb_path,
                    table_names=[name for name in exported_tables if name.startswith("mart_")],
                )

            if WAREHOUSE_EXPORTS_TOTAL is not None:
                WAREHOUSE_EXPORTS_TOTAL.labels(format=export_format, status="ok").inc()

            run = WarehouseExportRun(
                traffic_type=traffic_type,
                export_format=export_format,
                lookback_days=int(lookback_days),
                status="ok",
                raw_files=raw_files,
                mart_files=mart_files,
                exported_tables=exported_tables,
                metadata={
                    "duckdb_path": duckdb_path,
                    "export_root": str(root),
                    "clickhouse_enabled": bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED),
                    "clickhouse_tables": clickhouse_tables,
                },
                created_at=utc_now(),
            )
            await run.insert()
            return {
                "status": "ok",
                "format": export_format,
                "traffic_type": traffic_type,
                "lookback_days": int(lookback_days),
                "root": str(root),
                "duckdb_path": duckdb_path,
                "raw_files": raw_files,
                "mart_files": mart_files,
                "exported_tables": exported_tables,
                "clickhouse_tables": clickhouse_tables,
            }
        except Exception as exc:
            if WAREHOUSE_EXPORTS_TOTAL is not None:
                WAREHOUSE_EXPORTS_TOTAL.labels(format=export_format, status="error").inc()
            run = WarehouseExportRun(
                traffic_type=traffic_type,
                export_format=export_format,
                lookback_days=int(lookback_days),
                status="error",
                error=str(exc),
                created_at=utc_now(),
            )
            await run.insert()
            return {
                "status": "error",
                "format": export_format,
                "error": str(exc),
            }

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, default=str))
                handle.write("\n")
        return str(path)

    def _materialize_duckdb(
        self,
        *,
        raw_files: dict[str, str],
        marts_root: Path,
        traffic_type: str,
        lookback_days: int,
        export_parquet: bool,
    ) -> tuple[str, list[str], dict[str, str]]:
        import duckdb  # type: ignore

        duckdb_path = Path(settings.ANALYTICS_WAREHOUSE_DUCKDB_PATH).resolve()
        duckdb_path.parent.mkdir(parents=True, exist_ok=True)

        exported_tables: list[str] = []
        mart_files: dict[str, str] = {}
        with duckdb.connect(str(duckdb_path)) as conn:
            for table_name, file_path in raw_files.items():
                schema = self.RAW_TABLE_SCHEMAS.get(table_name, {})
                if Path(file_path).stat().st_size <= 0 and schema:
                    columns = ", ".join(f"{column} {column_type}" for column, column_type in schema.items())
                    conn.execute(f"CREATE OR REPLACE TABLE {table_name} ({columns})")
                else:
                    conn.execute(
                        f"""
                        CREATE OR REPLACE TABLE {table_name} AS
                        SELECT * FROM read_json_auto(?, ignore_errors=true);
                        """,
                        [file_path],
                    )
                exported_tables.append(table_name)

            for model_path in sorted(self._models_dir().glob("*.sql")):
                table_name = model_path.stem
                sql = self._render_sql(
                    model_path.read_text(encoding="utf-8"),
                    table_name=table_name,
                    traffic_type=traffic_type,
                    lookback_days=lookback_days,
                )
                conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS {sql}")
                exported_tables.append(table_name)
                if export_parquet:
                    out_path = marts_root / f"{table_name}.parquet"
                    conn.execute(f"COPY {table_name} TO ? (FORMAT PARQUET)", [str(out_path)])
                    mart_files[table_name] = str(out_path)

        return str(duckdb_path), exported_tables, mart_files

    def _clickhouse_table_name(self, table_name: str) -> str:
        safe_name = "".join(ch for ch in str(table_name or "").strip().lower() if ch.isalnum() or ch == "_")
        if not safe_name:
            raise ValueError("invalid_clickhouse_table")
        prefix = "".join(
            ch for ch in str(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_TABLE_PREFIX or "").strip().lower()
            if ch.isalnum() or ch == "_"
        )
        if safe_name.startswith("mart_") and prefix == "mart_":
            return safe_name
        return f"{prefix}{safe_name}" if prefix and not safe_name.startswith(prefix) else safe_name

    def _clickhouse_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "UInt8"
        if isinstance(value, int) and not isinstance(value, bool):
            return "Int64"
        if isinstance(value, float):
            return "Float64"
        if isinstance(value, datetime):
            return "DateTime64(6, 'UTC')"
        return "String"

    def _clickhouse_value(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, default=str, sort_keys=True)
        return value

    def _materialize_clickhouse(self, *, duckdb_path: str, table_names: list[str]) -> list[str]:
        import duckdb  # type: ignore
        import clickhouse_connect  # type: ignore

        host = (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST or "").strip()
        if not host:
            raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST is required when ClickHouse export is enabled.")

        client = clickhouse_connect.get_client(
            host=host,
            port=int(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT),
            username=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME or "default",
            password=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD or "",
            database=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE,
            secure=bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE),
        )

        materialized: list[str] = []
        with duckdb.connect(str(duckdb_path), read_only=True) as conn:
            for source_table in table_names:
                target_table = self._clickhouse_table_name(source_table)
                rows = conn.execute(f"SELECT * FROM {source_table}").fetchall()
                columns = [item[0] for item in conn.description or []]
                if not columns:
                    continue

                sample = rows[0] if rows else tuple("" for _ in columns)
                column_defs = [
                    f"`{column}` {self._clickhouse_type(sample[index])}"
                    for index, column in enumerate(columns)
                ]
                client.command(
                    f"CREATE TABLE IF NOT EXISTS `{target_table}` ({', '.join(column_defs)}) "
                    "ENGINE = MergeTree ORDER BY tuple()"
                )
                client.command(f"TRUNCATE TABLE `{target_table}`")
                if rows:
                    client.insert(
                        target_table,
                        [[self._clickhouse_value(value) for value in row] for row in rows],
                        column_names=columns,
                    )
                materialized.append(target_table)
        return materialized

    def list_available_marts(self) -> list[str]:
        return sorted(path.stem for path in self._models_dir().glob("*.sql"))

    def read_mart(self, mart_name: str, *, limit: int = 100) -> list[dict[str, Any]]:
        import duckdb  # type: ignore

        safe_name = "".join(ch for ch in str(mart_name or "").strip().lower() if ch.isalnum() or ch == "_")
        if safe_name not in set(self.list_available_marts()):
            raise ValueError("unknown_mart")
        safe_limit = max(1, min(int(limit), 500))
        duckdb_path = Path(settings.ANALYTICS_WAREHOUSE_DUCKDB_PATH).resolve()
        if not duckdb_path.exists():
            return []
        with duckdb.connect(str(duckdb_path), read_only=True) as conn:
            rows = conn.execute(f"SELECT * FROM {safe_name} LIMIT {safe_limit}").fetchall()
            columns = [item[0] for item in conn.description]
        return [dict(zip(columns, row)) for row in rows]

    async def latest_runs(self, *, limit: int = 20) -> list[WarehouseExportRun]:
        safe_limit = max(1, min(int(limit), 100))
        return await WarehouseExportRun.find_many().sort("-created_at").limit(safe_limit).to_list()

    async def freshness_status(self, *, required_marts: list[str] | None = None) -> dict[str, Any]:
        marts = list(required_marts or settings.ANALYTICS_WAREHOUSE_REQUIRED_MARTS or [])
        latest_rows = await WarehouseExportRun.find_many({"status": "ok"}).sort("-created_at").limit(1).to_list()
        latest = latest_rows[0] if latest_rows else None
        if latest is None:
            return {
                "status": "missing",
                "fresh": False,
                "required_marts": marts,
                "missing_marts": marts,
                "stale_marts": [],
                "max_staleness_minutes": int(settings.ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES),
                "latest_export_at": None,
                "age_minutes": None,
            }

        exported = set(latest.exported_tables or [])
        exported.update((latest.mart_files or {}).keys())
        missing = sorted(mart for mart in marts if mart not in exported)
        age_minutes = self._age_minutes(latest.created_at)
        max_staleness = max(1, int(settings.ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES))
        stale_marts = sorted(marts) if age_minutes > max_staleness else []
        fresh = not missing and not stale_marts
        return {
            "status": "fresh" if fresh else "stale",
            "fresh": fresh,
            "required_marts": marts,
            "missing_marts": missing,
            "stale_marts": stale_marts,
            "max_staleness_minutes": max_staleness,
            "latest_export_at": latest.created_at.isoformat(),
            "age_minutes": round(age_minutes, 3),
            "export_run_id": str(latest.id),
            "clickhouse_enabled": bool((latest.metadata or {}).get("clickhouse_enabled")),
            "clickhouse_tables": list((latest.metadata or {}).get("clickhouse_tables") or []),
            "bi_tool_url": (settings.ANALYTICS_BI_TOOL_URL or "").strip() or None,
        }

    async def assert_required_marts_fresh(self) -> dict[str, Any]:
        status = await self.freshness_status()
        if not bool(status.get("fresh")):
            raise RuntimeError(
                "Analytics warehouse marts are not fresh: "
                f"missing={status.get('missing_marts')}, stale={status.get('stale_marts')}, "
                f"age_minutes={status.get('age_minutes')}."
            )
        return status

    def _age_minutes(self, value: datetime) -> float:
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return max(0.0, (utc_now() - observed).total_seconds() / 60.0)


warehouse_export_service = WarehouseExportService()
