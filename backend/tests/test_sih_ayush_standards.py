"""The Ayush demand table, and the label that keeps it honest.

The problem statement is sponsored by the Ministry of Ayush and the All India
Institute of Ayurveda, and the product was answering it with a curriculum
signal about machine learning and Java. The corpus held 6 Ayush-related rows out
of 2,242, several of which were circulars rather than opportunities, and not one
student profile named an Ayush field.

Scraping cannot fix that. Thirty candidate sources were fetched and read the way
the extractor reads them - the Ministry, CCRAS, CCRUM, CCRYN, NIA, AIIA, ITRA,
MDNIY, NMPB, nine manufacturers and wellness employers, and NCS. Best yield was
seven rows, two of which were navigation. Ayush publishes vacancies as PDF
notices on notice boards.

So this sector's demand is a different kind of evidence, and the thing these
tests exist to protect is that it never stops being labelled as one. A share of
postings and a weight from an occupational standard are both legitimate; the
failure mode is rendering them identically, which is exactly how this repo
previously published a seeded constant as a measurement.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.sih_ayush_standards import (
    BAND_LABELS,
    COMPETENCIES,
    DEMAND_BASIS,
    ROLES,
    WEIGHTS,
    demand_rows,
    is_ayush_field,
    roles_requiring,
)
from app.services.skill_assessment_service import build_questionnaire
from app.services.skill_demand import normalise_skill


class TestTheCompetencySet(unittest.TestCase):
    def test_the_curriculum_subjects_are_present(self) -> None:
        skills = {item.skill for item in COMPETENCIES}
        for subject in ("kayachikitsa", "panchakarma", "dravyaguna", "rasashastra",
                        "swasthavritta", "shalya tantra", "agada tantra"):
            with self.subTest(subject=subject):
                self.assertIn(subject, skills)

    def test_every_competency_carries_its_evidence(self) -> None:
        # A requirement nobody can trace is an assertion, not a standard.
        for item in COMPETENCIES:
            with self.subTest(skill=item.skill):
                self.assertTrue(item.evidence_basis.strip())

    def test_no_competency_invents_a_document_code(self) -> None:
        # A citation nobody can follow is worse than none, and in a regulated
        # field it is the error that ends a conversation with a domain expert.
        for item in COMPETENCIES:
            with self.subTest(skill=item.skill):
                self.assertNotRegex(item.evidence_basis, r"\bQP\s*[-–]?\s*\d", "looks like an invented QP code")
                self.assertNotRegex(item.evidence_basis, r"\bNOS\s*[-–]?\s*\d", "looks like an invented NOS code")

    def test_the_skills_survive_the_platform_s_own_normalisation(self) -> None:
        # If normalise_skill rejected these, the demand table would be empty and
        # the assessment would ask about nothing.
        for item in COMPETENCIES:
            with self.subTest(skill=item.skill):
                self.assertEqual(normalise_skill(item.skill), item.skill)


class TestTheGapsWorthArguing(unittest.TestCase):
    """The signal only means something if it can find a real gap."""

    def test_some_required_competencies_are_taught_nowhere(self) -> None:
        # This is the curriculum argument the problem statement asks for. If
        # every requirement mapped to a subject, the platform would have nothing
        # to tell a department.
        untaught = [item.skill for item in COMPETENCIES if item.taught_in is None]
        self.assertTrue(untaught)
        self.assertIn("patient counselling", untaught)

    def test_a_gap_can_be_named_as_a_job(self) -> None:
        # "Nobody can evidence GMP compliance" is a statistic; "that closes the
        # Quality Control Officer route" is an argument.
        self.assertIn("Quality Control Officer", roles_requiring("gmp compliance"))
        self.assertEqual(roles_requiring("this is not a competency"), [])


class TestTheRowsAreLabelled(unittest.TestCase):
    def test_every_row_declares_its_basis(self) -> None:
        for row in demand_rows():
            with self.subTest(skill=row["skill"]):
                self.assertEqual(row["basis"], "occupational_standard")

    def test_rows_are_ordered_most_widely_required_first(self) -> None:
        shares = [float(row["share"]) for row in demand_rows()]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_the_basis_sentence_says_it_is_not_a_scrape(self) -> None:
        # This string is rendered above the table. It has to do the work.
        self.assertIn("not from scraped job postings", DEMAND_BASIS)

    def test_bands_are_ordinal_and_bounded(self) -> None:
        for band, weight in WEIGHTS.items():
            with self.subTest(band=band):
                self.assertIn(band, BAND_LABELS)
                self.assertGreater(weight, 0.0)
                self.assertLessEqual(weight, 1.0)


class TestTheQuestionnaireDoesNotLie(unittest.TestCase):
    """The defect this nearly shipped with.

    Every question used to be captioned "named in N live postings in this
    domain". Built over the Ayush table that reads "named in 0 live postings"
    beside a question the platform is insisting the student answers - a
    falsehood with a number in it, on the screen where a student decides whether
    to trust the next number.
    """

    def test_a_standards_row_is_not_described_as_postings(self) -> None:
        questions = build_questionnaire(demand_rows())
        self.assertTrue(questions)
        for question in questions:
            with self.subTest(skill=question.skill):
                self.assertNotIn("live posting", question.rationale)

    def test_a_standards_row_says_what_it_is(self) -> None:
        questions = build_questionnaire(demand_rows())
        self.assertTrue(any("graduate roles" in q.rationale for q in questions))

    def test_a_scraped_row_is_still_described_as_postings(self) -> None:
        # The change must not touch the domains that do have a posting feed.
        scraped = [{"skill": "python", "share": 0.31, "postings": 27, "is_soft": False}]
        questions = build_questionnaire(scraped)
        self.assertIn("named in 27 live postings", questions[0].rationale)


class TestDisciplineDetection(unittest.TestCase):
    """A BAMS student must not be handed an allopathic demand table.

    `domain` on a profile is one of five coarse buckets, so a BAMS student and
    an MBBS student both carry "Medicine". The discipline lives in the course or
    the specialisation, and that is what has to be read.
    """

    def test_the_ayush_degrees_are_recognised(self) -> None:
        for course in ("BAMS", "BHMS", "BUMS", "BNYS"):
            with self.subTest(course=course):
                self.assertTrue(is_ayush_field(course, None, "Medicine"))

    def test_every_ncism_subject_is_recognised_on_its_own(self) -> None:
        # Nine of the fourteen subjects offered at sign-up matched nothing
        # standing alone, so a student who recorded their subject and not their
        # degree got the wrong demand table.
        for subject in (
            "Kayachikitsa (General Medicine)",
            "Panchakarma",
            "Dravyaguna Vigyana (Materia Medica)",
            "Rasashastra evam Bhaishajya Kalpana",
            "Swasthavritta evam Yoga",
            "Shalya Tantra (Surgery)",
            "Shalakya Tantra (ENT and Ophthalmology)",
            "Prasuti Tantra evam Stri Roga",
            "Kaumarbhritya (Paediatrics)",
            "Agada Tantra (Toxicology)",
            "Roga Nidana (Diagnostics)",
            "Samhita and Siddhanta",
            "Rachana Sharira (Anatomy)",
            "Kriya Sharira (Physiology)",
        ):
            with self.subTest(subject=subject):
                self.assertTrue(is_ayush_field(subject))

    def test_allopathic_and_unrelated_fields_are_not_claimed(self) -> None:
        # The expensive direction. Claiming a field that is not Ayush would give
        # an MBBS or engineering cohort a curriculum signal about Panchakarma,
        # which is a worse failure than missing an Ayush student.
        for field in (
            "General Medicine", "Cardiology", "Neurosurgery", "Dentistry",
            "Nursing", "Physiotherapy", "Pharmacy", "Computer Science",
            "Anatomy", "Physiology", "Surgery", "Mechanical Engineering",
        ):
            with self.subTest(field=field):
                self.assertFalse(is_ayush_field(field))

    def test_it_reads_any_of_the_three_places_a_discipline_is_recorded(self) -> None:
        self.assertTrue(is_ayush_field("BAMS", None, None))
        self.assertTrue(is_ayush_field(None, "Panchakarma", None))
        self.assertFalse(is_ayush_field(None, None, "Medicine"))


class TestSingleDisciplineCohortsGetTheirOwnTable(unittest.TestCase):
    """An Ayurveda college measured against the tech market produced nothing.

    The cohort endpoint always used the whole-market demand table. For a mixed
    institution that is the honest choice and the docstring argues it well. For
    a single-discipline one it is simply the wrong table: crossed against twelve
    BAMS students it yielded zero rows, and the dashboard said "no skill has
    enough assessed students in common" - which reads as too little data and was
    really a comparison against a profession they are not entering.
    """

    def _resolve(self, rows):
        from app.api.api_v1.endpoints.academia import institution_domain_for_signal

        return institution_domain_for_signal(rows)

    def _student(self, course, spec, domain="Medicine"):
        return {"course": course, "course_specialization": spec, "domain": domain}

    def test_an_all_bams_cohort_uses_the_ayush_table(self) -> None:
        from app.services.sih_ayush_standards import AYUSH_DOMAIN

        rows = [self._student("BAMS", "Panchakarma")] * 12
        self.assertEqual(self._resolve(rows), AYUSH_DOMAIN)

    def test_a_mixed_cohort_still_uses_the_whole_market(self) -> None:
        # The behaviour that was already right must not change. A minority
        # discipline deciding the table for everyone else is the failure this
        # threshold exists to prevent.
        from app.services.skill_demand import GLOBAL_DOMAIN

        rows = [self._student("BAMS", "Panchakarma")] * 4 + [
            self._student("B.Tech", "Computer Science", "Engineering")
        ] * 8
        self.assertEqual(self._resolve(rows), GLOBAL_DOMAIN)

    def test_an_empty_cohort_does_not_raise(self) -> None:
        from app.services.skill_demand import GLOBAL_DOMAIN

        self.assertEqual(self._resolve([]), GLOBAL_DOMAIN)

    def test_the_threshold_is_a_large_majority(self) -> None:
        # Set deliberately high: below it the institution really is mixed.
        from app.api.api_v1.endpoints.academia import SINGLE_DISCIPLINE_SHARE

        self.assertGreaterEqual(SINGLE_DISCIPLINE_SHARE, 0.7)


class TestTheRolesAreReal(unittest.TestCase):
    def test_every_role_requires_something_defined(self) -> None:
        known = {item.skill for item in COMPETENCIES}
        for role in ROLES:
            with self.subTest(role=role.title):
                self.assertTrue(role.competencies)
                self.assertTrue(set(role.competencies) <= known)


if __name__ == "__main__":
    unittest.main()
