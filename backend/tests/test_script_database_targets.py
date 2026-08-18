"""Scripts must read whichever database is serving, not a hardcoded one.

Every script in `backend/scripts/` opened its own
`AsyncIOMotorClient(settings.MONGODB_URL)`. That was correct until the Postgres
cutover, after which each one silently pointed at an abandoned database whose
newest interaction is 2026-06-03.

The failure mode is the dangerous kind: nothing errors. Queries succeed, results
are simply empty or stale, and the job reports success. Three separate instances
were found in production before this test existed:

1. `publish_dataset_snapshot` published a README section headed "Verified
   Snapshot" describing the dead database.
2. `purge_aged_telemetry` reported a clean retention run having touched nothing.
3. `rebuild_analytics_warehouse` reported `status: ok` with `feature_rows: 0`,
   which meant the training data the ranker retrains on had quietly stopped
   being produced - and a release gate read that emptiness as "no drift".

`KNOWN_UNCONVERTED` is debt, not permission. The list may shrink and must never
grow: a new script that hardcodes Mongo fails this test rather than being
discovered months later by a number that looks wrong.
"""
from __future__ import annotations

from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

#: Scripts still connecting directly to Mongo. Converting one means deleting its
#: line here. Adding a line is not an option - convert the script instead.
KNOWN_UNCONVERTED = {
    "audit_incident_review_sla.py",
    "backfill_company_careers_scope.py",
    "backfill_missing_mongo_rows.py",  # compares both databases on purpose
    "backfill_opportunity_metadata.py",
    "backfill_opportunity_scope.py",
    "backfill_opportunity_trust.py",
    "backfill_traffic_provenance.py",
    "bootstrap_company_seeds.py",
    "bootstrap_demo_data.py",
    "bootstrap_ranking_pipeline.py",
    "check_warehouse_release_gate.py",
    "dedupe_probation_opportunities.py",
    "migrate_admin_identity.py",
    "publish_model_metadata.py",
    "publish_ranker_rollout_report.py",
    "publish_weekly_business_impact_scorecard.py",
    "publish_weekly_ds_scorecard.py",
    "publish_weekly_mlops_scorecard.py",
    "run_deduplication_scan.py",
    "run_model_lifecycle_pipeline.py",
    "seed_release_ml_gate_fixture.py",
    "seed_test_data.py",
    "simulate_persona_traffic.py",
    "test_backup_restore_drill.py",
    "train_nlp_model.py",
    "version_datasets.py",
}

MONGO_MARKERS = ("AsyncIOMotorClient(settings.MONGODB_URL", "MongoClient(")
BACKEND_AWARE = ("POSTGRES_ODM_ENABLED", "_script_db")


def hardcoded_scripts() -> set[str]:
    found: set[str] = set()
    for path in SCRIPTS_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(m in text for m in MONGO_MARKERS) and not any(m in text for m in BACKEND_AWARE):
            found.add(path.name)
    return found


class TestNoNewHardcodedMongo:
    def test_no_script_outside_the_known_list_hardcodes_mongo(self):
        new = hardcoded_scripts() - KNOWN_UNCONVERTED
        assert not new, (
            "These scripts connect to Mongo unconditionally, so under "
            "POSTGRES_ODM_ENABLED they read an abandoned database and report "
            "success on empty results:\n  "
            + "\n  ".join(sorted(new))
            + "\n\nUse scripts/_script_db.connect(models) instead."
        )

    def test_the_debt_list_only_shrinks(self):
        """A converted script must be removed from KNOWN_UNCONVERTED."""
        stale = KNOWN_UNCONVERTED - hardcoded_scripts()
        assert not stale, (
            "These are listed as unconverted but no longer hardcode Mongo. "
            "Delete them from KNOWN_UNCONVERTED:\n  " + "\n  ".join(sorted(stale))
        )

    def test_the_critical_paths_are_converted(self):
        """Training and release gates must never read the wrong database."""
        critical = {
            "train_learned_ranker.py",
            "check_ds_release_gates.py",
            "check_champion_challenger_gate.py",
            "check_real_traffic_rollout_readiness.py",
            "validate_data_health.py",
            "rebuild_analytics_warehouse.py",
            "publish_dataset_snapshot.py",
        }
        still_hardcoded = critical & hardcoded_scripts()
        assert not still_hardcoded, (
            "A model trained on, or a gate passed against, the wrong database is "
            "worse than a failure: " + ", ".join(sorted(still_hardcoded))
        )


class TestSharedHelper:
    def test_helper_exists_and_handles_both_backends(self):
        import _script_db  # noqa: F401  (scripts dir is on sys.path via conftest)

        assert hasattr(_script_db, "connect")
        assert hasattr(_script_db, "close")

    def test_close_tolerates_none(self):
        import _script_db

        _script_db.close(None)  # must not raise

    @pytest.mark.parametrize("name", sorted({
        "train_learned_ranker.py", "check_ds_release_gates.py",
        "check_champion_challenger_gate.py",
        "check_real_traffic_rollout_readiness.py", "validate_data_health.py",
    }))
    def test_converted_scripts_close_through_the_helper(self, name: str):
        """`client` is None under Postgres; a bare client.close() would raise."""
        text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        assert "client.close()" not in text.replace("_script_db.close(client)", "")
