"""Audience routing: which feed a scraped row belongs to.

Every scraper here pointed at student roles, and each other role's feed was
carved out of that one corpus by matching words in a title. The academician feed
was seven items out of nearly two thousand, and "Market Research Intern" was one
of the things the matcher had to be taught to reject. Filtering cannot add what
the corpus does not contain: an FDP is advertised by AICTE, not by a job board.

Audience travels seed -> discovered source -> opportunity, so a feed is a lookup
rather than a guess. The properties worth pinning are the two that fail quietly.

An unrecognised or missing audience must resolve to "student". Every row in this
database predating the column came from a student-facing scraper, so that is a
statement of fact - and the alternative, dropping such a row into a feed nobody
reads, loses it silently.

And normalisation must never widen a match. If a bad value resolved to something
that matched every audience, one mislabelled source would put faculty postings
in front of students and vice versa, which looks like a populated feed.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.audiences import (
    DEFAULT_AUDIENCE,
    FACULTY,
    INSTITUTION,
    KNOWN_AUDIENCES,
    STUDENT,
    audience_matches,
    normalise_audience,
)


class TestAudienceVocabulary(unittest.TestCase):
    def test_three_audiences_exist(self) -> None:
        for name in (STUDENT, FACULTY, INSTITUTION):
            with self.subTest(name=name):
                self.assertIn(name, KNOWN_AUDIENCES)

    def test_default_is_student(self) -> None:
        # Not a convenience: every pre-existing row came from a student scraper.
        self.assertEqual(DEFAULT_AUDIENCE, STUDENT)


class TestNormalisation(unittest.TestCase):
    def test_known_values_survive(self) -> None:
        for value in (STUDENT, FACULTY, INSTITUTION):
            with self.subTest(value=value):
                self.assertEqual(normalise_audience(value), value)

    def test_casing_and_spacing_are_forgiven(self) -> None:
        self.assertEqual(normalise_audience("  FACULTY "), FACULTY)
        self.assertEqual(normalise_audience("Institution"), INSTITUTION)

    def test_missing_or_unknown_falls_back_to_student(self) -> None:
        # A scraped row with a junk audience belongs in the feed a human reads,
        # not in one nobody opens.
        for value in (None, "", "   ", "nonsense", "recruiter", "123"):
            with self.subTest(value=value):
                self.assertEqual(normalise_audience(value), STUDENT)

    def test_normalisation_never_raises(self) -> None:
        # This runs inside extraction batches; raising would fail the batch over
        # one bad row.
        for value in (None, 0, [], {}, object()):
            with self.subTest(value=value):
                self.assertIn(normalise_audience(value), KNOWN_AUDIENCES)


class TestMatching(unittest.TestCase):
    def test_a_row_matches_only_its_own_audience(self) -> None:
        # The dangerous failure. A value that matched everything would put
        # faculty postings in the student feed and look like it was working.
        self.assertTrue(audience_matches(FACULTY, FACULTY))
        self.assertFalse(audience_matches(FACULTY, STUDENT))
        self.assertFalse(audience_matches(FACULTY, INSTITUTION))

    def test_legacy_rows_match_the_student_feed_only(self) -> None:
        for wanted, expected in ((STUDENT, True), (FACULTY, False), (INSTITUTION, False)):
            with self.subTest(wanted=wanted):
                self.assertEqual(audience_matches(None, wanted), expected)

    def test_a_junk_audience_does_not_leak_into_another_feed(self) -> None:
        self.assertFalse(audience_matches("nonsense", FACULTY))
        self.assertTrue(audience_matches("nonsense", STUDENT))


class TestModelsCarryTheColumn(unittest.TestCase):
    """The column has to exist on all three models or the chain breaks silently.

    Audience is only useful if it survives the whole path. A model missing the
    field does not error - it just never propagates, and the feed downstream
    quietly falls back to the keyword matcher this replaced.
    """

    def test_every_model_in_the_chain_has_an_audience_field(self) -> None:
        from app.models.opportunity import Opportunity
        from app.models.source_discovery import CompanySeed, DiscoveredSource

        for model in (CompanySeed, DiscoveredSource, Opportunity):
            with self.subTest(model=model.__name__):
                self.assertIn("audience", model.model_fields)

    def test_every_model_defaults_to_student(self) -> None:
        from app.models.opportunity import Opportunity
        from app.models.source_discovery import CompanySeed, DiscoveredSource

        for model in (CompanySeed, DiscoveredSource, Opportunity):
            with self.subTest(model=model.__name__):
                self.assertEqual(model.model_fields["audience"].default, STUDENT)


class TestDensityVocabularyIsAudienceAware(unittest.TestCase):
    """"An opportunity" means different words to different audiences.

    opportunity_density carries the largest weight in qualification, 25 of 100,
    and counted only jobs vocabulary. An accreditation body or ranking portal
    advertises schemes, calls for proposals and collaborations, never vacancies,
    so it scored zero - and with every other check perfect the total landed on
    exactly 59.0 against a threshold of 60. NIRF and AIM both did. No institution
    source could ever have passed, and the rejection read
    "low_qualification_score", which sounds like a bad site rather than a
    vocabulary that does not describe it.
    """

    def _terms(self, audience: str):
        from app.services.source_discovery import SourceQualificationService

        return SourceQualificationService.DENSITY_TERMS[audience]

    def test_every_audience_has_a_vocabulary(self) -> None:
        for audience in (STUDENT, FACULTY, INSTITUTION):
            with self.subTest(audience=audience):
                self.assertTrue(self._terms(audience))

    def test_student_vocabulary_is_unchanged(self) -> None:
        # The student corpus is the one that was working; this change must not
        # move its scores at all.
        self.assertEqual(
            self._terms(STUDENT), ("apply", "intern", "job", "role", "opening", "hiring")
        )

    def test_institution_vocabulary_covers_what_institutions_publish(self) -> None:
        terms = self._terms(INSTITUTION)
        for expected in ("scheme", "call for", "proposal", "collaborat", "accredit"):
            with self.subTest(term=expected):
                self.assertIn(expected, terms)

    def test_faculty_vocabulary_covers_academic_postings(self) -> None:
        terms = self._terms(FACULTY)
        for expected in ("faculty", "fellowship", "professor", "vacanc"):
            with self.subTest(term=expected):
                self.assertIn(expected, terms)

    def test_unknown_audience_falls_back_to_student_vocabulary(self) -> None:
        from app.services.source_discovery import SourceQualificationService

        service = SourceQualificationService
        self.assertEqual(
            service.DENSITY_TERMS.get(normalise_audience("nonsense")),
            service.DENSITY_TERMS[STUDENT],
        )


if __name__ == "__main__":
    unittest.main()
