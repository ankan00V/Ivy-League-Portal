from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.metrics import WAREHOUSE_EXPORTS_TOTAL
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry


class WarehouseExportService:
    def _enabled(self) -> bool:
        export_format = str(settings.ANALYTICS_WAREHOUSE_EXPORT_FORMAT or "").strip().lower()
        return bool(settings.ANALYTICS_WAREHOUSE_EXPORT_ENABLED) and export_format not in {"", "disabled"}

    def _safe_root(self) -> Path:
        return Path(settings.ANALYTICS_WAREHOUSE_EXPORT_ROOT).resolve()

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
            if export_format in {"duckdb", "duckdb_parquet"}:
                duckdb_path, exported_tables = self._materialize_duckdb(
                    raw_files=raw_files,
                    marts_root=marts_root,
                    traffic_type=traffic_type,
                    lookback_days=lookback_days,
                    export_parquet=export_format == "duckdb_parquet",
                )

            if WAREHOUSE_EXPORTS_TOTAL is not None:
                WAREHOUSE_EXPORTS_TOTAL.labels(format=export_format, status="ok").inc()
            return {
                "status": "ok",
                "format": export_format,
                "traffic_type": traffic_type,
                "lookback_days": int(lookback_days),
                "root": str(root),
                "duckdb_path": duckdb_path,
                "raw_files": raw_files,
                "exported_tables": exported_tables,
            }
        except Exception as exc:
            if WAREHOUSE_EXPORTS_TOTAL is not None:
                WAREHOUSE_EXPORTS_TOTAL.labels(format=export_format, status="error").inc()
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
    ) -> tuple[str, list[str]]:
        import duckdb  # type: ignore

        duckdb_path = Path(settings.ANALYTICS_WAREHOUSE_DUCKDB_PATH).resolve()
        duckdb_path.parent.mkdir(parents=True, exist_ok=True)

        exported_tables: list[str] = []
        with duckdb.connect(str(duckdb_path)) as conn:
            for table_name, file_path in raw_files.items():
                conn.execute(
                    f"""
                    CREATE OR REPLACE TABLE {table_name} AS
                    SELECT * FROM read_json_auto(?, ignore_errors=true);
                    """,
                    [file_path],
                )
                exported_tables.append(table_name)

            conn.execute(
                """
                CREATE OR REPLACE TABLE mart_daily_metrics AS
                SELECT *
                FROM analytics_daily
                ORDER BY date DESC;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TABLE mart_funnel_metrics AS
                SELECT *
                FROM analytics_funnels
                ORDER BY date DESC;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TABLE mart_cohort_metrics AS
                SELECT *
                FROM analytics_cohorts
                ORDER BY cohort_date DESC, days_since_cohort ASC;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TABLE mart_training_dataset AS
                SELECT
                    row_key,
                    date,
                    user_id,
                    opportunity_id,
                    ranking_mode,
                    experiment_key,
                    experiment_variant,
                    traffic_type,
                    rank_position,
                    match_score,
                    features,
                    labels,
                    source_event_id
                FROM feature_store_rows
                ORDER BY date DESC;
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE TABLE mart_metadata AS
                SELECT
                    ? AS traffic_type,
                    ? AS lookback_days,
                    now() AS materialized_at;
                """,
                [traffic_type, int(lookback_days)],
            )
            exported_tables.extend(
                [
                    "mart_daily_metrics",
                    "mart_funnel_metrics",
                    "mart_cohort_metrics",
                    "mart_training_dataset",
                    "mart_metadata",
                ]
            )

            if export_parquet:
                for table_name in exported_tables:
                    out_path = marts_root / f"{table_name}.parquet"
                    conn.execute(f"COPY {table_name} TO ? (FORMAT PARQUET)", [str(out_path)])

        return str(duckdb_path), exported_tables


warehouse_export_service = WarehouseExportService()
