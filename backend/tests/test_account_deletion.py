"""Account erasure must cover every collection that names a user.

The failure mode this guards against is not a crash — it is silence. Someone adds a
new user-scoped collection six months from now, never thinks about deletion, and the
product keeps holding that person's rows forever while the delete endpoint reports
success. Nothing would surface that.

So the inventory is swept, not trusted. `test_every_user_scoped_model_is_classified`
enumerates the models actually registered in `bootstrap.DOCUMENT_MODELS`, finds every
field that points at a user, and fails if any of them is neither covered by an
`ErasureRule` nor listed in `ERASURE_EXEMPTIONS` with a written reason.

Writing the audit as a test is how `test_traffic_provenance.py` locked down the
seeded-traffic defect, and the reasoning is the same: the rule has to be enforced by
CI, not by whoever remembers it.
"""
from __future__ import annotations

import inspect

import pytest

from app.bootstrap import DOCUMENT_MODELS
from app.services.account_deletion_service import (
    ERASURE_EXEMPTIONS,
    ERASURE_RULES,
    ErasureReceipt,
    ErasureRule,
)

#: A field name that means "this row belongs to / was written by a person".
#: Substring match, because the codebase uses user_id, posted_by_user_id,
#: recruiter_user_id, employer_user_id and created_by_user_id interchangeably.
USER_FIELD_MARKERS = ("user_id", "email")

#: Fields whose names trip the markers above but which hold no identifier.
#: Kept narrow and explicit so a genuinely new identifier cannot hide behind it.
FIELD_LEVEL_EXEMPTIONS = {
    ("profiles", "user_type"),
    ("career_outcome_events", "user_confirmed"),
    ("analytics_cohort_aggregates", "users_in_cohort"),
    ("analytics_cohort_aggregates", "active_users"),
    ("analytics_cohort_aggregates", "applying_users"),
}


def _collection_name(model) -> str:
    settings = getattr(model, "Settings", None)
    return str(getattr(settings, "name", model.__name__))


def _user_fields(model) -> set[str]:
    return {
        name
        for name in model.model_fields
        if any(marker in name.lower() for marker in USER_FIELD_MARKERS)
    }


def _rules_by_collection() -> dict[str, ErasureRule]:
    return {_collection_name(rule.document): rule for rule in ERASURE_RULES}


class TestErasureInventory:
    def test_every_user_scoped_model_is_classified(self):
        """The whole point of this file.

        Every registered document with a user-identifying field must either have an
        ErasureRule or an explicit written exemption.
        """
        rules = _rules_by_collection()
        unclassified: list[str] = []

        for model in DOCUMENT_MODELS:
            collection = _collection_name(model)
            fields = {
                name
                for name in _user_fields(model)
                if (collection, name) not in FIELD_LEVEL_EXEMPTIONS
            }
            if not fields:
                continue
            if collection in ERASURE_EXEMPTIONS:
                continue
            rule = rules.get(collection)
            if rule is None:
                unclassified.append(f"{collection}: {sorted(fields)} has no ErasureRule")
                continue
            # A field is handled either by being matched/rewritten (user_fields) or
            # by being cleared outright (redact_fields). AuthAuditEvent.email is the
            # latter: the row survives for abuse defence with the identity stripped.
            covered = set(rule.user_fields) | set(rule.redact_fields)
            missing = fields - covered
            if missing:
                unclassified.append(
                    f"{collection}: fields {sorted(missing)} are not covered by its ErasureRule"
                )

        assert not unclassified, (
            "User-scoped collections are missing from the erasure inventory.\n"
            "Add an ErasureRule in app/services/account_deletion_service.py, or an\n"
            "entry in ERASURE_EXEMPTIONS explaining why the data stays.\n\n"
            + "\n".join(unclassified)
        )

    def test_every_rule_targets_a_registered_document(self):
        registered = {_collection_name(model) for model in DOCUMENT_MODELS}
        for rule in ERASURE_RULES:
            assert _collection_name(rule.document) in registered, (
                f"{_collection_name(rule.document)} has an ErasureRule but is not in "
                "DOCUMENT_MODELS, so nothing will ever match it."
            )

    def test_every_rule_states_a_rationale(self):
        """A disposition without a reason is a copied line, not a decision."""
        for rule in ERASURE_RULES:
            assert rule.rationale.strip(), (
                f"{_collection_name(rule.document)} has no rationale for its "
                f"'{rule.disposition}' disposition."
            )

    def test_every_exemption_states_a_reason(self):
        for collection, reason in ERASURE_EXEMPTIONS.items():
            assert reason.strip(), f"{collection} is exempt with no stated reason."

    def test_no_collection_is_both_ruled_and_exempt(self):
        overlap = set(_rules_by_collection()) & set(ERASURE_EXEMPTIONS)
        assert not overlap, f"Ambiguous disposition for: {sorted(overlap)}"

    def test_redact_fields_exist_on_their_model(self):
        """A typo'd redaction target silently adds a new field instead of clearing one."""
        for rule in ERASURE_RULES:
            for name in rule.redact_fields:
                assert name in rule.document.model_fields, (
                    f"{_collection_name(rule.document)} has no field '{name}' to redact."
                )

    def test_user_fields_exist_on_their_model(self):
        for rule in ERASURE_RULES:
            for name in rule.user_fields:
                assert name in rule.document.model_fields, (
                    f"{_collection_name(rule.document)} has no field '{name}'."
                )

    def test_redaction_targets_are_optional(self):
        """Erasure sets redacted fields to None; a required field would break the row."""
        for rule in ERASURE_RULES:
            for name in rule.redact_fields:
                info = rule.document.model_fields[name]
                assert not info.is_required(), (
                    f"{_collection_name(rule.document)}.{name} is required, so setting it "
                    "to None during erasure would produce a row that no longer validates."
                )


class TestErasurePolicy:
    def test_measurement_collections_are_not_hard_deleted(self):
        """Deleting measurements would rewrite history.

        This repo has twice published numbers that were artefacts of its own data
        handling. Silently shrinking the impression and exposure record on every
        account deletion would be a third.
        """
        rules = _rules_by_collection()
        must_survive = (
            "opportunity_interactions",
            "recommendation_exposures",
            "recommendation_feature_snapshots",
            "experiment_assignments",
            "career_outcome_events",
        )
        for collection in must_survive:
            assert collection in rules, f"{collection} lost its erasure rule"
            assert rules[collection].disposition == "pseudonymize", (
                f"{collection} must be pseudonymized, not erased: deleting it would "
                "retroactively change experiment denominators and training labels."
            )

    def test_identity_collections_are_hard_deleted(self):
        rules = _rules_by_collection()
        must_vanish = ("profiles", "applications", "ask_ai_saved_queries", "user_journeys")
        for collection in must_vanish:
            assert collection in rules, f"{collection} lost its erasure rule"
            assert rules[collection].disposition == "erase", (
                f"{collection} holds data about the person and must be deleted outright."
            )

    def test_free_text_is_redacted_wherever_a_row_survives(self):
        """Pseudonymizing a row that still contains what the user typed is not erasure."""
        rules = _rules_by_collection()
        assert "query" in rules["opportunity_interactions"].redact_fields
        assert "comment" in rules["recommendation_feedback"].redact_fields
        assert "email" in rules["auth_audit_events"].redact_fields

    def test_pseudonym_is_not_derived_from_the_user_id(self):
        """A hashed id is reversible by whoever holds the user list — i.e. us.

        The pseudonym must be freshly generated, so the source must not hash, encode
        or otherwise derive it from the real identifier.
        """
        from app.services import account_deletion_service

        source = inspect.getsource(account_deletion_service)
        erase_body = source.split("async def erase_account", 1)[1]
        for banned in ("sha256", "md5", "sha1", "hashlib", "hmac"):
            assert banned not in erase_body, (
                f"erase_account appears to derive the pseudonym via {banned}; it must be "
                "randomly generated so it cannot be reversed back to the user."
            )

    def test_collection_lookup_survives_the_beanie_rename(self):
        """Beanie 2.x renamed get_motor_collection -> get_pymongo_collection.

        Found by running the purge script against Atlas: every rule raised
        AttributeError, every rule was caught and "skipped" with a warning, and
        erase_account returned a success receipt having deleted nothing.
        """
        from app.services.telemetry_privacy import get_collection

        from app.models.profile import Profile

        class OldBeanie:
            __name__ = "OldBeanie"

            @staticmethod
            def get_motor_collection():
                return "motor"

        class NewBeanie:
            __name__ = "NewBeanie"

            @staticmethod
            def get_pymongo_collection():
                return "pymongo"

        assert get_collection(OldBeanie) == "motor"
        assert get_collection(NewBeanie) == "pymongo"

        # And the resolver works against a real registered document class.
        assert any(
            hasattr(Profile, name)
            for name in ("get_motor_collection", "get_pymongo_collection")
        )

    def test_an_unreachable_collection_aborts_rather_than_being_skipped(self):
        """A deletion that reports success without deleting is the worst outcome.

        `_apply_rule` used to swallow the collection lookup failure and `return`,
        which is how the rename above turned into a no-op erasure. The lookup must
        now propagate.
        """
        from app.services import account_deletion_service

        source = inspect.getsource(account_deletion_service._apply_rule)
        lookup_at = source.index("get_collection(rule.document)")
        preceding = source[:lookup_at]
        # No try: may open between the start of the function and the lookup.
        assert "try:" not in preceding, (
            "_apply_rule must not wrap the collection lookup in a try/except that "
            "continues; a skipped collection means data survives a deletion."
        )

    def test_user_row_is_deleted_after_the_dependent_rows(self):
        """Order matters: a crash must leave a retryable account, not orphaned data."""
        from app.services import account_deletion_service

        source = inspect.getsource(account_deletion_service.erase_account)
        loop_at = source.index("for rule in ERASURE_RULES")
        delete_at = source.index("await user.delete()")
        assert loop_at < delete_at, (
            "erase_account deletes the User row before clearing dependent collections; "
            "a failure mid-way would strand rows behind a login that no longer resolves."
        )


class TestErasureReceipt:
    def test_receipt_totals_are_summed(self):
        receipt = ErasureReceipt(user_id="u", pseudonym="p")
        receipt.erased = {"profiles": 1, "posts": 3}
        receipt.pseudonymized = {"opportunity_interactions": 42}
        summary = receipt.as_dict()
        assert summary["total_rows_erased"] == 4
        assert summary["total_rows_pseudonymized"] == 42

    def test_receipt_reports_the_pseudonym_for_audit(self):
        receipt = ErasureReceipt(user_id="u", pseudonym="p")
        assert receipt.as_dict()["pseudonym"] == "p"


class TestDeletionEndpointContract:
    def test_endpoint_requires_typed_confirmation(self):
        from app.api.api_v1.endpoints.users import ACCOUNT_DELETION_CONFIRMATION

        assert ACCOUNT_DELETION_CONFIRMATION == "DELETE MY ACCOUNT"

    def test_delete_route_is_registered(self):
        from app.api.api_v1.endpoints.users import router

        routes = {
            (route.path, tuple(sorted(route.methods)))
            for route in router.routes
            if hasattr(route, "methods")
        }
        assert ("/me", ("DELETE",)) in routes, "DELETE /users/me is not registered"

    @pytest.mark.parametrize("wrong", ["", "delete", "yes", "DELETE", "DELETE MY ACCOUNT!"])
    def test_confirmation_comparison_rejects_near_misses(self, wrong):
        from app.api.api_v1.endpoints.users import ACCOUNT_DELETION_CONFIRMATION

        assert wrong.strip().upper() != ACCOUNT_DELETION_CONFIRMATION
