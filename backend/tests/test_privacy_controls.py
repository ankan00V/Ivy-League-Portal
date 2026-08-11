"""Consent has to change behaviour, and telemetry has to stop naming people.

Three things are pinned here.

1. **Consent gates something real.** `consent_data_processing` was previously stored,
   scored toward profile completeness, and read by nothing. A toggle that changes no
   behaviour is worse than no toggle, because it tells the student they have a choice
   they do not have.
2. **Minimized fields stay gone.** The profile no longer collects gender, pronouns,
   date of birth, or street-level address. It is very easy for one of those to come
   back through an autofill helper or a copied schema.
3. **Warehouse exports carry pseudonyms.** The ClickHouse copy must not hold ids that
   resolve against the application database.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.services.privacy_consent_service import (
    PRIVACY_POLICY_VERSION,
    apply_consent_change,
    filter_rows_by_consent,
    has_active_consent,
)
from app.services.telemetry_privacy import (
    pseudonymize_rows,
    retention_cutoff,
    warehouse_pseudonym,
)


class _FakeProfile:
    """Stand-in for a Profile: Beanie documents need an initialised collection."""

    def __init__(self, **kwargs):
        self.consent_data_processing = kwargs.get("consent_data_processing", False)
        self.consent_data_processing_at = kwargs.get("consent_data_processing_at")
        self.consent_policy_version = kwargs.get("consent_policy_version")
        self.consent_withdrawn_at = kwargs.get("consent_withdrawn_at")


class TestConsentPredicate:
    def test_no_profile_is_not_consent(self):
        assert has_active_consent(None) is False

    def test_flag_off_is_not_consent(self):
        assert has_active_consent(_FakeProfile(consent_data_processing=False)) is False

    def test_flag_on_without_a_policy_version_is_not_consent(self):
        """The exact shape of the old bug: a bare True with nothing behind it.

        Every profile that predates versioned consent has the flag set and no version.
        Treating that as agreement would grandfather in consent to a policy those
        students never saw.
        """
        assert has_active_consent(_FakeProfile(consent_data_processing=True)) is False

    def test_consent_to_a_superseded_policy_is_not_consent(self):
        profile = _FakeProfile(consent_data_processing=True, consent_policy_version="1999-01-01")
        assert has_active_consent(profile) is False

    def test_current_policy_version_is_consent(self):
        profile = _FakeProfile(
            consent_data_processing=True,
            consent_policy_version=PRIVACY_POLICY_VERSION,
        )
        assert has_active_consent(profile) is True

    def test_withdrawal_beats_the_flag(self):
        profile = _FakeProfile(
            consent_data_processing=True,
            consent_policy_version=PRIVACY_POLICY_VERSION,
            consent_withdrawn_at=datetime.now(timezone.utc),
        )
        assert has_active_consent(profile) is False


class TestConsentRecording:
    def test_granting_stamps_version_and_timestamp(self):
        profile = _FakeProfile()
        apply_consent_change(profile, granted=True)
        assert profile.consent_data_processing is True
        assert profile.consent_policy_version == PRIVACY_POLICY_VERSION
        assert profile.consent_data_processing_at is not None
        assert profile.consent_withdrawn_at is None
        assert has_active_consent(profile) is True

    def test_withdrawal_keeps_the_original_grant_timestamp(self):
        """When consent was held and when it ended is what makes an export auditable."""
        profile = _FakeProfile()
        apply_consent_change(profile, granted=True)
        granted_at = profile.consent_data_processing_at

        apply_consent_change(profile, granted=False)
        assert profile.consent_data_processing is False
        assert profile.consent_withdrawn_at is not None
        assert profile.consent_data_processing_at == granted_at
        assert has_active_consent(profile) is False

    def test_regranting_clears_the_withdrawal(self):
        profile = _FakeProfile()
        apply_consent_change(profile, granted=True)
        apply_consent_change(profile, granted=False)
        apply_consent_change(profile, granted=True)
        assert profile.consent_withdrawn_at is None
        assert has_active_consent(profile) is True


class TestConsentFiltering:
    def test_rows_without_consent_are_dropped(self):
        rows = [{"user_id": "yes"}, {"user_id": "no"}]
        kept = filter_rows_by_consent(rows, permitted_user_ids={"yes"})
        assert kept == [{"user_id": "yes"}]

    def test_rows_with_no_user_pass_through(self):
        """Anonymous serving telemetry has no person to have withheld consent."""
        rows = [{"user_id": None}, {"other": 1}, {"user_id": ""}]
        assert len(filter_rows_by_consent(rows, permitted_user_ids=set())) == 3

    def test_empty_permission_set_drops_every_user_row(self):
        """Fail closed: if consent cannot be resolved, nothing user-linked exports."""
        rows = [{"user_id": "a"}, {"user_id": "b"}]
        assert filter_rows_by_consent(rows, permitted_user_ids=set()) == []

    def test_object_ids_are_compared_as_strings(self):
        from beanie import PydanticObjectId

        uid = PydanticObjectId()
        kept = filter_rows_by_consent([{"user_id": uid}], permitted_user_ids={str(uid)})
        assert len(kept) == 1


class TestWarehousePseudonymization:
    def test_pseudonym_is_stable_and_distinct(self):
        assert warehouse_pseudonym("abc") == warehouse_pseudonym("abc")
        assert warehouse_pseudonym("abc") != warehouse_pseudonym("abd")

    def test_pseudonym_does_not_contain_the_original_id(self):
        assert "abc" not in warehouse_pseudonym("abc")

    def test_missing_ids_stay_missing(self):
        assert warehouse_pseudonym(None) is None
        assert warehouse_pseudonym("") is None

    def test_rows_are_not_mutated_in_place(self):
        original = {"user_id": "abc", "reward": 1.0}
        [transformed] = pseudonymize_rows([original])
        assert original["user_id"] == "abc"
        assert transformed["user_id"] != "abc"
        assert transformed["reward"] == 1.0

    def test_rows_without_a_user_key_are_untouched(self):
        assert pseudonymize_rows([{"count": 3}]) == [{"count": 3}]

    def test_export_applies_consent_and_pseudonymization_before_writing(self):
        """Guards the ordering: filtering after the JSONL write would leak to disk."""
        from app.services.warehouse_export_service import WarehouseExportService

        source = inspect.getsource(WarehouseExportService.export)
        consent_at = source.index("filter_rows_by_consent")
        pseudo_at = source.index("pseudonymize_rows")
        write_at = source.index("raw_files = {")
        assert consent_at < write_at, "consent filtering must happen before rows are written"
        assert pseudo_at < write_at, "pseudonymization must happen before rows are written"


class TestTelemetryRetention:
    def test_cutoff_is_in_the_past(self):
        cutoff = retention_cutoff()
        assert cutoff is not None
        assert cutoff < datetime.now(timezone.utc)

    def test_cutoff_honours_the_reference_time(self):
        now = datetime(2026, 8, 5, tzinfo=timezone.utc)
        cutoff = retention_cutoff(now=now)
        from app.core.config import settings

        assert cutoff == now - timedelta(days=settings.TELEMETRY_RAW_RETENTION_DAYS)

    def test_retention_can_be_disabled(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "TELEMETRY_RAW_RETENTION_DAYS", 0, raising=False)
        assert retention_cutoff() is None

    def test_retention_rewrites_rather_than_deletes(self):
        """Deleting aged rows would shrink historical impression counts."""
        from app.services import telemetry_privacy

        source = inspect.getsource(telemetry_privacy.purge_aged_telemetry)
        assert "delete_many" not in source, (
            "purge_aged_telemetry must not delete telemetry; it unlinks it."
        )
        assert "update_many" in source

    def test_retention_script_defaults_to_dry_run(self):
        script = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "scripts"
            / "purge_aged_telemetry.py"
        )
        source = script.read_text()
        assert 'action="store_true"' in source
        assert "apply=args.apply" in source


class TestProfileMinimization:
    #: Removed 2026-08-05. Nothing read any of them.
    REMOVED_FIELDS = (
        "gender",
        "pronouns",
        "date_of_birth",
        "current_address_line1",
        "current_address_landmark",
        "current_address_pincode",
        "permanent_address_line1",
        "permanent_address_landmark",
        "permanent_address_pincode",
    )

    @pytest.mark.parametrize("field", REMOVED_FIELDS)
    def test_removed_fields_are_not_on_the_model(self, field):
        from app.models.profile import Profile

        assert field not in Profile.model_fields, (
            f"{field} was removed in the data-minimization pass and must not come back "
            "without a documented product reason."
        )

    @pytest.mark.parametrize("field", REMOVED_FIELDS)
    def test_removed_fields_are_not_accepted_by_the_api(self, field):
        from app.api.api_v1.endpoints.users import ProfileUpdate

        assert field not in ProfileUpdate.model_fields

    @pytest.mark.parametrize("field", REMOVED_FIELDS)
    def test_removed_fields_are_not_returned_by_the_api(self, field):
        from app.api.api_v1.endpoints.users import ProfileResponse

        assert field not in ProfileResponse.model_fields

    @pytest.mark.parametrize("field", ("current_address_region", "permanent_address_region"))
    def test_region_survives_because_ranking_uses_it(self, field):
        """The counterpart assertion: minimization must not eat a live feature.

        `feature_builder._profile_location_tokens` reads both region fields.
        """
        from app.models.profile import Profile

        assert field in Profile.model_fields

    def test_username_no_longer_encodes_a_birth_year(self):
        """Handles are shown on the public leaderboard; they leaked the birth year."""
        from app.services import username_service

        source = inspect.getsource(username_service)
        assert "date_of_birth" not in source
        assert "_extract_birth_year_suffix" not in source

    def test_purge_script_protects_the_ranking_fields(self):
        from importlib import import_module
        import sys
        from pathlib import Path

        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        module = import_module("purge_minimized_profile_fields")

        assert set(module.PROTECTED_FIELDS) == {
            "current_address_region",
            "permanent_address_region",
        }
        assert not set(module.PURGE_FIELDS) & set(module.PROTECTED_FIELDS)


class TestRetentionTargetsTheServingDatabase:
    """Retention must run against whichever store is actually serving.

    `pg_documents.install` patches the Beanie query API but not the raw-collection
    accessor, so `get_collection()` still returns a **Mongo** handle under the
    Postgres ODM. The retention job used that handle, which meant it reported a
    clean run while never touching the live database — the same silent
    wrong-store failure the dataset snapshot had.
    """

    def test_purge_dispatches_on_the_active_backend(self):
        import inspect

        from app.services import telemetry_privacy

        source = inspect.getsource(telemetry_privacy.purge_aged_telemetry)
        assert "POSTGRES_ODM_ENABLED" in source, (
            "purge_aged_telemetry must dispatch on the active backend; otherwise it "
            "silently retains against the abandoned Mongo database."
        )
        dispatch_at = source.index("POSTGRES_ODM_ENABLED")
        mongo_at = source.index("get_collection(")
        assert dispatch_at < mongo_at, "the backend check must precede the Mongo path"

    def test_postgres_path_never_deletes_rows(self):
        """Deleting aged rows would shrink historical impression counts."""
        import inspect

        from app.services import telemetry_privacy

        source = inspect.getsource(telemetry_privacy._purge_aged_telemetry_postgres)
        assert "DELETE" not in source.upper().replace("DELETED", "")
        assert "UPDATE app.opportunity_interactions" in source

    def test_postgres_path_clears_the_feature_payload(self):
        """`features` is 53% of the table heap and unread past the training window."""
        import inspect

        from app.services import telemetry_privacy

        source = inspect.getsource(telemetry_privacy._purge_aged_telemetry_postgres)
        assert "features = NULL" in source
        assert "query = NULL" in source

    def test_retention_window_outlives_every_consumer(self):
        """Must exceed the longest lookback, or retention destroys training data."""
        from app.core.config import settings

        assert settings.TELEMETRY_RAW_RETENTION_DAYS > settings.MLOPS_RETRAIN_LOOKBACK_DAYS
        assert settings.TELEMETRY_RAW_RETENTION_DAYS > settings.MLOPS_GUARDRAIL_LOOKBACK_DAYS
        assert settings.TELEMETRY_RAW_RETENTION_DAYS > settings.MLOPS_DRIFT_LOOKBACK_DAYS
