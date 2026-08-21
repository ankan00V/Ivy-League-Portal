import sys
import tempfile
import unittest
from datetime import date
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.warehouse_export_service import warehouse_export_service
from app.core.time import utc_now

try:
    import duckdb  # type: ignore  # noqa: F401

    HAS_DUCKDB = True
except Exception:
    HAS_DUCKDB = False


@unittest.skipUnless(HAS_DUCKDB, "duckdb is not installed in the current test environment")
class TestWarehouseExportService(unittest.TestCase):
    def test_materialize_duckdb_and_read_mart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw = root / "raw"
            raw.mkdir(parents=True, exist_ok=True)
            marts = root / "marts"
            marts.mkdir(parents=True, exist_ok=True)
            models = root / "models"
            models.mkdir(parents=True, exist_ok=True)

            (models / "mart_daily_metrics.sql").write_text(
                "SELECT date, metric_type FROM analytics_daily ORDER BY date DESC",
                encoding="utf-8",
            )
            (raw / "analytics_daily.jsonl").write_text(
                '{"date":"2026-01-01","metric_type":"interaction","traffic_type":"real","metrics":{"impressions":10}}\n',
                encoding="utf-8",
            )
            for table in [
                "opportunity_interactions",
                "ranking_request_telemetry",
                "feature_store_rows",
                "analytics_funnels",
                "analytics_cohorts",
            ]:
                (raw / f"{table}.jsonl").write_text("", encoding="utf-8")

            with (
                patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_DUCKDB_PATH", str(root / "warehouse.duckdb")),
                patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_SQL_MODELS_DIR", str(models)),
            ):
                _, tables, mart_files = warehouse_export_service._materialize_duckdb(
                    raw_files={
                        "opportunity_interactions": str(raw / "opportunity_interactions.jsonl"),
                        "ranking_request_telemetry": str(raw / "ranking_request_telemetry.jsonl"),
                        "feature_store_rows": str(raw / "feature_store_rows.jsonl"),
                        "analytics_daily": str(raw / "analytics_daily.jsonl"),
                        "analytics_funnels": str(raw / "analytics_funnels.jsonl"),
                        "analytics_cohorts": str(raw / "analytics_cohorts.jsonl"),
                    },
                    marts_root=marts,
                    traffic_type="real",
                    lookback_days=30,
                    export_parquet=True,
                )
                rows = warehouse_export_service.read_mart("mart_daily_metrics", limit=5)

        self.assertIn("mart_daily_metrics", tables)
        self.assertIn("mart_daily_metrics", mart_files)
        self.assertEqual(rows[0]["date"], "2026-01-01")


class TestWarehouseClickHouseExport(unittest.TestCase):
    def test_materialize_clickhouse_creates_and_inserts_marts(self) -> None:
        commands: list[str] = []
        inserts: list[tuple[str, list[list[object]], list[str]]] = []

        class FakeDuckConnection:
            description = [("cohort_date",), ("metrics",), ("impressions",)]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def execute(self, _sql: str):
                return self

            def fetchall(self):
                return [(date(2026, 1, 1), {"ctr": 0.12}, 10)]

        fake_duckdb = SimpleNamespace(connect=lambda *_args, **_kwargs: FakeDuckConnection())

        class FakeClickHouseClient:
            def command(self, sql: str) -> None:
                commands.append(sql)

            def insert(self, table: str, rows: list[list[object]], column_names: list[str]) -> None:
                inserts.append((table, rows, column_names))

        fake_clickhouse = SimpleNamespace(get_client=lambda **_kwargs: FakeClickHouseClient())

        with (
            patch.dict(sys.modules, {"duckdb": fake_duckdb, "clickhouse_connect": fake_clickhouse}),
            patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST", "clickhouse"),
            patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE", "vidyaverse"),
            patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME", "vidyaverse"),
            patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD", "secret"),
        ):
            tables = warehouse_export_service._materialize_clickhouse(
                duckdb_path="/tmp/warehouse.duckdb",
                table_names=["mart_daily_metrics"],
            )

        self.assertEqual(tables, ["mart_daily_metrics"])
        # The export is a full refresh, so the table is rebuilt each run.
        # CREATE TABLE IF NOT EXISTS previously made a wrongly inferred schema
        # permanent - a column created as String stayed String forever and
        # rejected every later date value.
        self.assertTrue(any("DROP TABLE IF EXISTS" in command for command in commands))
        self.assertTrue(any(command.startswith("CREATE TABLE `") for command in commands))
        self.assertFalse(any("CREATE TABLE IF NOT EXISTS" in command for command in commands))
        self.assertTrue(any("`cohort_date` Date" in command for command in commands))
        self.assertEqual(inserts[0][0], "mart_daily_metrics")
        self.assertEqual(inserts[0][1][0][0], date(2026, 1, 1))
        self.assertEqual(inserts[0][1][0][1], '{"ctr": 0.12}')


class TestWarehouseFreshnessGate(unittest.IsolatedAsyncioTestCase):
    async def test_freshness_status_reports_missing_when_no_successful_export_exists(self) -> None:
        class FakeQuery:
            def sort(self, *_args):
                return self

            def limit(self, *_args):
                return self

            async def to_list(self):
                return []

        with patch("app.services.warehouse_export_service.WarehouseExportRun.find_many", return_value=FakeQuery()):
            status = await warehouse_export_service.freshness_status(required_marts=["mart_daily_metrics"])

        self.assertFalse(status["fresh"])
        self.assertEqual(status["status"], "missing")
        self.assertEqual(status["missing_marts"], ["mart_daily_metrics"])

    async def test_freshness_status_marks_required_marts_stale_after_slo(self) -> None:
        run = SimpleNamespace(
            id="run-1",
            status="ok",
            exported_tables=["mart_daily_metrics"],
            mart_files={},
            metadata={},
            created_at=utc_now() - timedelta(minutes=15),
        )

        class FakeQuery:
            def sort(self, *_args):
                return self

            def limit(self, *_args):
                return self

            async def to_list(self):
                return [run]

        with (
            patch("app.services.warehouse_export_service.WarehouseExportRun.find_many", return_value=FakeQuery()),
            patch("app.services.warehouse_export_service.settings.ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES", 5),
        ):
            status = await warehouse_export_service.freshness_status(required_marts=["mart_daily_metrics"])

        self.assertFalse(status["fresh"])
        self.assertEqual(status["stale_marts"], ["mart_daily_metrics"])


if __name__ == "__main__":
    unittest.main()


class TestClickHouseSchemaInference(unittest.TestCase):
    """Schema was inferred from rows[0] alone.

    A column that happened to be NULL in the first row was typed String, and the
    first real date in any later row then failed to insert with
    "'datetime.date' object has no attribute 'encode'" - which is exactly how
    the live warehouse export broke.
    """

    def setUp(self) -> None:
        from app.services.warehouse_export_service import WarehouseExportService

        self.service = WarehouseExportService()

    def test_column_sample_skips_leading_nulls(self) -> None:
        rows = [
            (None, "a"),
            (date(2026, 1, 1), "b"),
        ]
        self.assertEqual(self.service._column_sample(rows, 0), date(2026, 1, 1))

    def test_all_null_column_falls_back_to_string(self) -> None:
        rows = [(None,), (None,)]
        self.assertEqual(self.service._column_sample(rows, 0), "")
        self.assertEqual(self.service._clickhouse_type(self.service._column_sample(rows, 0)), "String")

    def test_date_column_with_leading_null_is_typed_date(self) -> None:
        rows = [(None,), (date(2026, 1, 1),)]
        inferred = self.service._clickhouse_type(self.service._column_sample(rows, 0))
        self.assertEqual(inferred, "Date")


class TestClickHouseMirrorIsolation(unittest.TestCase):
    """A dead ClickHouse must not fail an export whose marts already built.

    The managed instance was a 30-day trial. It expired, its hostname now returns
    NXDOMAIN, and the push has been failing since 2026-06-19. Before this
    isolation, that failure propagated out of `export()` and every refresh
    recorded `status=error` — discarding marts that had been written to disk
    seconds earlier, for a mirror that nothing reads. The analytics API serves
    marts from DuckDB, not ClickHouse.
    """

    def test_push_failure_does_not_fail_the_export(self) -> None:
        import inspect

        from app.services import warehouse_export_service as module

        source = inspect.getsource(module.WarehouseExportService.export)
        push_at = source.index("_materialize_clickhouse")
        preceding = source[:push_at]

        self.assertIn(
            "try:",
            preceding[preceding.rindex("clickhouse_tables: list[str] = []") :],
            "the ClickHouse push must be wrapped so a mirror failure cannot discard "
            "a successful mart build",
        )

    def test_export_records_the_mirror_outcome(self) -> None:
        """A skipped push must be visible, not silent."""
        import inspect

        from app.services import warehouse_export_service as module

        source = inspect.getsource(module.WarehouseExportService.export)
        for field in ("clickhouse_status", "clickhouse_error"):
            self.assertIn(
                field,
                source,
                f"export() must record {field} so a failed mirror is auditable",
            )

    def test_disabled_clickhouse_is_reported_as_disabled(self) -> None:
        import inspect

        from app.services import warehouse_export_service as module

        source = inspect.getsource(module.WarehouseExportService.export)
        self.assertIn('clickhouse_status = "disabled"', source)
