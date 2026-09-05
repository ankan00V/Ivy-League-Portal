"""Academician and institution roles.

The institution role is the only one on this platform that reads data about
other people, so most of these tests are about containment rather than
correctness. Two failures matter more than the rest:

A cohort that matches too little is a visible bug - the dashboard reads low and
someone investigates. A cohort that matches too much is a disclosure, and it
looks exactly like the feature working. The name normaliser has to collapse the
four spellings of one university found in this database while never merging two
different institutions, and those two requirements pull in opposite directions.

Aggregates over a tiny cohort are not aggregates. An average across two students
identifies both, so below a floor the answer is a refusal that says so - not an
empty dashboard, which reads as "your students have done nothing" and means
something entirely different.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.account_types import (
    CANDIDATE,
    EMPLOYER,
    FACULTY,
    INSTITUTION,
    KNOWN_ACCOUNT_TYPES,
    account_type_enabled,
)
from app.services.academia_service import (
    MIN_COHORT_SIZE,
    email_domain,
    normalise_institution_name,
    student_matches_institution,
    summarise_cohort,
)


class TestAccountTypes(unittest.TestCase):
    def test_all_four_roles_exist(self) -> None:
        for role in (CANDIDATE, EMPLOYER, FACULTY, INSTITUTION):
            with self.subTest(role=role):
                self.assertIn(role, KNOWN_ACCOUNT_TYPES)

    def test_candidates_are_never_gated(self) -> None:
        # Students are the product; a flag that could switch them off is a foot-gun.
        self.assertTrue(account_type_enabled(CANDIDATE))

    def test_unknown_type_is_not_enabled(self) -> None:
        self.assertFalse(account_type_enabled("recruiter"))
        self.assertFalse(account_type_enabled(""))
        self.assertFalse(account_type_enabled(None))


class TestInstitutionNameMatching(unittest.TestCase):
    LPU_SPELLINGS = (
        "LOVELY PROFESSIONAL UNIVERSITY, PHAGWARA, PUNJAB",
        "LOVELY PROFESSIONAL UNIVERSITY",
        "Lovely Professional University, Phagwara, Punjab",
        "Lovely Professional University",
    )

    def test_the_four_real_spellings_collapse(self) -> None:
        # Taken verbatim from the accounts in this database.
        keys = {normalise_institution_name(name) for name in self.LPU_SPELLINGS}
        self.assertEqual(len(keys), 1, f"expected one key, got {keys}")

    def test_different_institutions_never_collide(self) -> None:
        # The dangerous direction. Stripping structural words over-strips short
        # names: "National Institute of Technology" and "National University"
        # both reduce to "national" without the guard, which would put one
        # institution's students in another's dashboard.
        pairs = (
            ("National Institute of Technology", "National University"),
            ("Delhi Technological University", "Delhi University"),
            ("Indian Institute of Technology Delhi", "Indian Institute of Science"),
            ("Madras Medical College", "Madras Christian College"),
        )
        for left, right in pairs:
            with self.subTest(pair=(left, right)):
                self.assertNotEqual(
                    normalise_institution_name(left),
                    normalise_institution_name(right),
                )

    def test_blank_name_is_blank_key(self) -> None:
        # A blank key must never match another blank key into a shared cohort.
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(normalise_institution_name(value), "")


class TestCohortMembership(unittest.TestCase):
    def test_email_domain_matches(self) -> None:
        match = student_matches_institution(
            student_email="student@lpu.in",
            student_college=None,
            institution_domain="lpu.in",
            institution_name="Lovely Professional University",
        )
        self.assertTrue(match.matched)
        self.assertEqual(match.reason, "email_domain")

    def test_college_name_matches_a_personal_mailbox(self) -> None:
        # Three of five students in this database signed up on gmail. Requiring
        # the college domain would drop the majority of every cohort.
        match = student_matches_institution(
            student_email="student@gmail.com",
            student_college="Lovely Professional University, Phagwara, Punjab",
            institution_domain="lpu.in",
            institution_name="LOVELY PROFESSIONAL UNIVERSITY",
        )
        self.assertTrue(match.matched)
        self.assertEqual(match.reason, "college_name")

    def test_unrelated_student_does_not_match(self) -> None:
        match = student_matches_institution(
            student_email="student@gmail.com",
            student_college="Indian Institute of Technology Delhi",
            institution_domain="lpu.in",
            institution_name="Lovely Professional University",
        )
        self.assertFalse(match.matched)

    def test_blank_institution_matches_nobody(self) -> None:
        # An institution that has set neither name nor domain must get an empty
        # cohort, not everybody.
        match = student_matches_institution(
            student_email="student@gmail.com",
            student_college=None,
            institution_domain="",
            institution_name="",
        )
        self.assertFalse(match.matched)

    def test_blank_student_college_does_not_match_blank_institution(self) -> None:
        match = student_matches_institution(
            student_email="student@gmail.com",
            student_college="",
            institution_domain="",
            institution_name="",
        )
        self.assertFalse(match.matched)

    def test_email_domain_extraction(self) -> None:
        self.assertEqual(email_domain("A.Student@LPU.in"), "lpu.in")
        self.assertEqual(email_domain("nonsense"), "")
        self.assertEqual(email_domain(None), "")


class TestCohortAggregation(unittest.TestCase):
    def _rows(self, count: int, **overrides):
        row = {
            "matched_by": "email_domain",
            "profile_complete": True,
            "incoscore": 60.0,
            "readiness": 50.0,
            "gaps": [{"skill": "docker", "priority": 0.1}],
            "applications": 2,
        }
        row.update(overrides)
        return [dict(row) for _ in range(count)]

    def test_small_cohort_is_refused_with_a_reason(self) -> None:
        aggregate, refusal = summarise_cohort(self._rows(MIN_COHORT_SIZE - 1))
        self.assertIsNone(aggregate)
        self.assertIsNotNone(refusal)
        self.assertIn(str(MIN_COHORT_SIZE), refusal)

    def test_refusal_is_distinguishable_from_no_activity(self) -> None:
        # The whole point: "too few students to anonymise" and "students with
        # nothing recorded" must not both render as an empty dashboard.
        _aggregate, refusal = summarise_cohort([])
        self.assertIsNotNone(refusal)

    def test_cohort_at_the_floor_is_reported(self) -> None:
        aggregate, refusal = summarise_cohort(self._rows(MIN_COHORT_SIZE))
        self.assertIsNone(refusal)
        self.assertIsNotNone(aggregate)
        self.assertEqual(aggregate.cohort_size, MIN_COHORT_SIZE)

    def test_averages_ignore_missing_values_rather_than_counting_them_as_zero(self) -> None:
        # A student who has not taken the assessment must not drag the cohort
        # average down as if they scored zero.
        rows = self._rows(MIN_COHORT_SIZE)
        rows[0]["readiness"] = None
        aggregate, _ = summarise_cohort(rows)
        self.assertEqual(aggregate.average_readiness, 50.0)
        self.assertEqual(aggregate.assessments_taken, MIN_COHORT_SIZE - 1)

    def test_all_missing_averages_report_none_not_zero(self) -> None:
        rows = self._rows(MIN_COHORT_SIZE, readiness=None, incoscore=None)
        aggregate, _ = summarise_cohort(rows)
        self.assertIsNone(aggregate.average_readiness)
        self.assertIsNone(aggregate.average_incoscore)

    def test_gaps_are_ranked_across_the_cohort(self) -> None:
        rows = self._rows(MIN_COHORT_SIZE)
        rows[0]["gaps"] = [{"skill": "kubernetes", "priority": 5.0}]
        aggregate, _ = summarise_cohort(rows)
        self.assertEqual(aggregate.top_gaps[0]["skill"], "kubernetes")
        self.assertEqual(aggregate.top_gaps[0]["students_affected"], 1)

    def test_participation_counts_students_not_applications(self) -> None:
        rows = self._rows(MIN_COHORT_SIZE)
        rows[0]["applications"] = 0
        aggregate, _ = summarise_cohort(rows)
        self.assertEqual(aggregate.students_with_applications, MIN_COHORT_SIZE - 1)
        self.assertEqual(aggregate.applications_total, (MIN_COHORT_SIZE - 1) * 2)


class TestFacultyOpportunityMatching(unittest.TestCase):
    """Faculty must not be handed the student feed with a new label.

    A single loose term list pulled 73 results out of the live corpus and most
    were wrong - every one of the rejections below is a real title it matched.
    The failure is invisible from the outside: the portal looks populated, and
    only a reader who knows what an FDP is can tell it is nonsense.
    """

    def _opportunity(self, title: str, opportunity_type: str = "Job"):
        return SimpleNamespace(
            title=title, opportunity_type=opportunity_type, portal_category=None
        )

    def _match(self, title: str, opportunity_type: str = "Job") -> bool:
        from app.api.api_v1.endpoints.academia import _looks_faculty_facing

        return _looks_faculty_facing(self._opportunity(title, opportunity_type))

    def test_real_faculty_openings_match(self) -> None:
        for title in (
            "Faculty Development Programme on Machine Learning",
            "FDP on Outcome Based Education",
            "Assistant Professor - Department of Ayurveda",
            "Postdoctoral Research Associate",
            "Consultancy project with industry partner",
            "Industrial Training for Engineering Faculty",
        ):
            with self.subTest(title=title):
                self.assertTrue(self._match(title), title)

    def test_student_roles_are_rejected(self) -> None:
        # Verbatim titles the loose matcher accepted.
        for title in (
            "Market Research Intern",
            "Finance Research Analyst",
            "Area Vice President, South Europe",
        ):
            with self.subTest(title=title):
                self.assertFalse(self._match(title), title)

    def test_weak_terms_need_academic_context(self) -> None:
        # "research" alone describes half the job market.
        self.assertFalse(self._match("Research Analyst, Retail Banking"))
        self.assertTrue(self._match("Research Fellowship at the Institute of Science"))

    def test_a_student_marker_overrides_a_strong_term(self) -> None:
        # An internship assisting a professor is still an internship.
        self.assertFalse(self._match("Intern - Professor's Research Lab"))

    def test_empty_text_does_not_match(self) -> None:
        self.assertFalse(self._match("", ""))


if __name__ == "__main__":
    unittest.main()
