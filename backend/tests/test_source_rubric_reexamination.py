"""A source rejected by a rule that has since been fixed must be asked again.

This is the defect behind every scoring bug this pipeline has had, and it is
worse than any of them individually. The qualification batch reads sources in
`discovered` and `qualified` only, so nothing rejected is ever revisited. Fixing
a check therefore does nothing for the sources the check was wrong about: they
keep the rejection, and the reason on them names a fault that no longer exists.

Three times now:

  * four academic sources scored 36 on reachability because the fetcher asked
    for a hostname nobody serves;
  * every institution source capped at exactly 59.0 against a threshold of 60,
    because the density check counted jobs vocabulary only;
  * every non-student source scored 0 of 10 on cross-source validation, a check
    the first source of any audience cannot satisfy by construction.

The re-examination has to be narrow in two directions or it becomes its own
problem. It must not re-admit safety verdicts, and it must not re-fetch the
whole rejection pile on every batch forever.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.source_rubric import (
    PERMANENT_REJECTIONS,
    QUALIFICATION_RUBRIC_VERSION,
    REEXAMINABLE_REJECTIONS,
    is_reexaminable,
    rejection_kind,
)

OLD = QUALIFICATION_RUBRIC_VERSION - 1


class TestReasonParsing(unittest.TestCase):
    def test_the_measured_value_is_stripped(self) -> None:
        # Reasons carry the number that produced them, which is useful to a
        # human and must not make the reason unmatchable.
        self.assertEqual(rejection_kind("low_qualification_score:59.0"), "low_qualification_score")
        self.assertEqual(rejection_kind("too_few_opportunities:1 (confidence 0.91 passed)"), "too_few_opportunities")

    def test_missing_reason_is_handled(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(rejection_kind(value), "")


class TestTheThreeHistoricalBugs(unittest.TestCase):
    """Each of these is a real rejection this pipeline issued and never revisited."""

    def test_the_59_point_0_cap_is_reexaminable(self) -> None:
        self.assertTrue(is_reexaminable("low_qualification_score:59.0", rubric_version=OLD))

    def test_the_www_reachability_failure_is_reexaminable(self) -> None:
        self.assertTrue(is_reexaminable("reachability", rubric_version=OLD))

    def test_a_thin_extraction_is_reexaminable(self) -> None:
        self.assertTrue(is_reexaminable("low_extraction_confidence:0.42", rubric_version=OLD))
        self.assertTrue(is_reexaminable("too_few_opportunities:1", rubric_version=OLD))

    def test_a_probation_failure_on_trust_is_reexaminable(self) -> None:
        # Trust scoring is one of the things that changed, so a source rejected
        # on its trust score was rejected by the old rubric.
        self.assertTrue(is_reexaminable("probation_failed:trust=50.1,parse_rate=1.00", rubric_version=OLD))


class TestSafetyVerdictsAreNotScores(unittest.TestCase):
    """Re-examination must never walk the crawler back somewhere the guard closed."""

    def test_spam_is_never_reexamined(self) -> None:
        self.assertFalse(is_reexaminable("spam_signals", rubric_version=0))

    def test_every_permanent_reason_stays_permanent(self) -> None:
        for reason in PERMANENT_REJECTIONS:
            with self.subTest(reason=reason):
                self.assertFalse(is_reexaminable(reason, rubric_version=0))

    def test_the_two_sets_do_not_overlap(self) -> None:
        # An overlap would make the outcome depend on which check ran first.
        self.assertEqual(REEXAMINABLE_REJECTIONS & PERMANENT_REJECTIONS, frozenset())


class TestItIsAnAllowList(unittest.TestCase):
    def test_an_unrecognised_reason_is_not_reexamined(self) -> None:
        # A reason added later must be argued onto the list deliberately. The
        # dangerous default is the permissive one: a new safety verdict would
        # otherwise be re-admitted the moment it shipped.
        self.assertFalse(is_reexaminable("some_future_reason", rubric_version=0))


class TestItRunsOnce(unittest.TestCase):
    def test_a_current_rubric_verdict_is_not_reexamined(self) -> None:
        # Without this the batch re-fetches every rejected source on every run,
        # which is a crawl of the whole rejection pile dressed up as a bug fix.
        self.assertFalse(
            is_reexaminable("low_qualification_score:59.0", rubric_version=QUALIFICATION_RUBRIC_VERSION)
        )

    def test_a_future_rubric_verdict_is_not_reexamined(self) -> None:
        self.assertFalse(
            is_reexaminable("reachability", rubric_version=QUALIFICATION_RUBRIC_VERSION + 1)
        )

    def test_an_unstamped_source_is_eligible(self) -> None:
        # Rows predating the column carry 0, which honestly means "we do not
        # know which rubric judged this" - the answer that earns one look.
        self.assertTrue(is_reexaminable("reachability", rubric_version=None))
        self.assertTrue(is_reexaminable("reachability", rubric_version=0))


class TestModelCarriesTheColumn(unittest.TestCase):
    def test_discovered_source_has_rubric_version(self) -> None:
        from app.models.source_discovery import DiscoveredSource

        self.assertIn("rubric_version", DiscoveredSource.model_fields)

    def test_it_defaults_to_zero_not_current(self) -> None:
        # Defaulting to the current version would silently write off the entire
        # existing backlog, which is the only reason this column exists.
        from app.models.source_discovery import DiscoveredSource

        self.assertEqual(DiscoveredSource.model_fields["rubric_version"].default, 0)


if __name__ == "__main__":
    unittest.main()
