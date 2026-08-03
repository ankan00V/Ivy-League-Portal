"""Seeded traffic must never be counted as real.

This is the regression test for the defect that produced
`docs/portfolio/real_traffic_rollout_readiness.md` claiming 260 real impressions and
a +13.8pp CTR win for the `ml` ranker, at a time when actual non-seed traffic was
1,402 impressions and zero clicks.

Two independent causes, both covered here:

1. `bootstrap_ranking_pipeline.py` wrote interaction rows without setting
   `traffic_type`, and the model default is "real".
2. Three separate filters treated a blank `traffic_type` as real "for backward
   compatibility", so any row predating the field also counted as real.

A third cause lived in CI: `seed_release_ml_gate_fixture.py` explicitly wrote
`traffic_type="real"` on its fixture rows, and `release-blocking-ml-gates.yml`
seeded it and then measured it. That one is covered by
`test_ci_fixture_is_labelled_simulated`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.traffic import (
    matches_traffic_type,
    normalize_traffic_type,
    traffic_type_query,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


class TestRealTrafficPredicate:
    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_traffic_type_is_not_real(self, blank):
        """The whole bug in one assertion.

        A row whose provenance is unknown must not be counted as a real student.
        Release gates fail closed: under-counting delays a promotion, over-counting
        promotes a model on evidence that does not exist.
        """
        assert matches_traffic_type(blank, "real") is False

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_traffic_type_is_not_simulated_either(self, blank):
        assert matches_traffic_type(blank, "simulated") is False

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_traffic_type_still_matches_all(self, blank):
        assert matches_traffic_type(blank, "all") is True

    def test_real_matches_real(self):
        assert matches_traffic_type("real", "real") is True
        assert matches_traffic_type("  REAL  ", "real") is True

    def test_simulated_never_counts_as_real(self):
        assert matches_traffic_type("simulated", "real") is False
        assert matches_traffic_type("simulated", "simulated") is True

    def test_unknown_filter_matches_nothing(self):
        assert matches_traffic_type("real", "nonsense") is False

    def test_normalize(self):
        assert normalize_traffic_type(None) == ""
        assert normalize_traffic_type("  Real ") == "real"


class TestQueryPredicateParity:
    """The Mongo filter and the Python predicate must agree.

    They are used interchangeably across services, so a divergence would reopen the
    exact hole this test exists to close.
    """

    @pytest.mark.parametrize("stored", ["real", "simulated", "", None])
    @pytest.mark.parametrize("wanted", ["real", "simulated", "all"])
    def test_query_and_predicate_agree(self, stored, wanted):
        query = traffic_type_query(wanted)
        if not query:
            matches_query = True
        else:
            matches_query = normalize_traffic_type(stored) == query["traffic_type"]
        assert matches_query == matches_traffic_type(stored, wanted)

    def test_real_query_does_not_admit_missing_field(self):
        """Guards the specific Mongo shape that caused this.

        experiment_analytics_service used to build
        {"$or": [{"traffic_type": "real"}, {"traffic_type": {"$exists": False}}, ...]}
        which matched every legacy seeded row.
        """
        query = traffic_type_query("real")
        assert query == {"traffic_type": "real"}
        assert "$or" not in query
        assert "$exists" not in str(query)


class TestSeedScriptsLabelTheirOwnRows:
    """Static guards. A seeder that forgets to label itself recreates the bug."""

    def test_bootstrap_ranking_pipeline_tags_simulated(self):
        src = (BACKEND_ROOT / "scripts" / "bootstrap_ranking_pipeline.py").read_text()
        constructions = src.count("OpportunityInteraction(")
        tagged = src.count('traffic_type="simulated"')
        assert constructions > 0, "expected the seeder to build interaction rows"
        assert tagged == constructions, (
            f"bootstrap_ranking_pipeline.py builds {constructions} OpportunityInteraction "
            f"rows but only tags {tagged} as simulated. Untagged rows inherit the model "
            f'default of "real" and get counted as genuine student traffic.'
        )

    def test_ci_fixture_is_labelled_simulated(self):
        """seed_release_ml_gate_fixture.py must never write traffic_type="real".

        release-blocking-ml-gates.yml seeds this fixture and then runs the parity
        gate over it. If the fixture claims to be real traffic, CI publishes a
        product claim it invented moments earlier.
        """
        src = (BACKEND_ROOT / "scripts" / "seed_release_ml_gate_fixture.py").read_text()
        assert 'traffic_type="real"' not in src, (
            "seed_release_ml_gate_fixture.py writes traffic_type=\"real\". It seeds a "
            "deterministic CI fixture, so its rows must be labelled simulated."
        )
        assert 'traffic_type="simulated"' in src


class TestNoServiceTreatsBlankAsReal:
    """Sweeps the codebase for the fail-open shape returning anywhere."""

    def test_no_in_blank_real_set_literal(self):
        offenders = []
        for path in (BACKEND_ROOT / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'in\s*\{\s*""\s*,\s*"real"\s*\}', text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, (
            "these treat a blank traffic_type as real, which counts seeded rows as "
            f"genuine student activity: {offenders}"
        )

    def test_no_mongo_exists_false_escape_hatch(self):
        offenders = []
        for path in (BACKEND_ROOT / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if '"traffic_type"' in line and "$exists" in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()}")
        assert not offenders, (
            "these admit rows with no traffic_type into a provenance-filtered query: "
            f"{offenders}"
        )


class TestCiWorkflowDeclaresItsProvenance:
    def test_release_gates_workflow_passes_simulated(self):
        """The seeding job must measure 'simulated', not 'real'."""
        wf = (REPO_ROOT / ".github" / "workflows" / "release-blocking-ml-gates.yml").read_text()
        assert "seed_release_ml_gate_fixture.py" in wf
        for script in (
            "check_real_traffic_rollout_readiness.py",
            "check_champion_challenger_gate.py",
            "check_ds_release_gates.py",
        ):
            for line in wf.splitlines():
                if script in line:
                    assert "--traffic-type simulated" in line, (
                        f"{script} runs in the seeding workflow without "
                        f"--traffic-type simulated, so it will report fixture data "
                        f"as a real-traffic result: {line.strip()}"
                    )

    def test_production_cron_does_not_seed(self):
        """The cron that reads production must never seed its own evidence."""
        wf = (REPO_ROOT / ".github" / "workflows" / "real-traffic-rollout-readiness.yml").read_text()
        assert "seed_release_ml_gate_fixture" not in wf
        assert "--traffic-type simulated" not in wf
