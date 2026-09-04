"""Trust was scored against one rubric written for student jobs.

Measured across every non-student source in probation, the pattern was the same
on all four: field completeness a perfect 20 of 20, extraction confidence 19-21
of 25 - the parsing was working - and then relevance 6.0-9.0 of 20 and
legitimacy 0-5 of 15. Totals landed at 49.77 to 57.05 against an auto-promote
gate of 70 and a reject floor of 55. Three of the four were one probation run
from being written off as bad sources.

None of them were bad. The rubric was asking a government research council
whether it mentioned a stipend, whether its name appeared in a list of consumer
technology brands, and whether its postings matched postings from an audience
whose corpus was empty. Those are three questions an academic source cannot pass
however good it is.

These tests pin the vocabulary per audience and the two structural fixes:
accreditation-controlled domains as a legitimacy signal, and a cold-start value
for a check no first source can satisfy.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.audiences import FACULTY, INSTITUTION, STUDENT
from app.services.source_discovery import TrustScoringEngine, _infer_opportunity_type

ENGINE = TrustScoringEngine()


def sample(**overrides):
    row = {
        "title": "Sample",
        "company": "Org",
        "location": "New Delhi, India",
        "apply_url": "https://example.ac.in/x",
        "description_preview": "",
        "opportunity_type": "job",
    }
    row.update(overrides)
    return row


class TestRelevanceSpeaksEachAudiencesLanguage(unittest.TestCase):
    def test_a_faculty_posting_scores_on_the_faculty_rubric(self) -> None:
        rows = [
            sample(
                title="Advertisement for the post of Assistant Professor",
                description_preview="Applications are invited for Assistant Professor, pay level 10.",
                opportunity_type="faculty",
            )
        ]
        faculty_score = ENGINE._relevance_score(rows, audience=FACULTY)
        student_score = ENGINE._relevance_score(rows, audience=STUDENT)
        self.assertGreater(
            faculty_score,
            student_score,
            "a professorship must read as more relevant to faculty than to students",
        )

    def test_an_institution_scheme_scores_on_the_institution_rubric(self) -> None:
        rows = [
            sample(
                title="Call for Proposals under the Institutional Development Scheme",
                description_preview="Colleges and universities may submit a proposal for a grant.",
                opportunity_type="proposal",
            )
        ]
        self.assertGreater(
            ENGINE._relevance_score(rows, audience=INSTITUTION),
            ENGINE._relevance_score(rows, audience=STUDENT),
        )

    def test_the_student_rubric_is_unchanged(self) -> None:
        # The student corpus is the one that was working. This change must not
        # move a single student source's score.
        rows = [
            sample(
                title="Software Engineering Internship",
                description_preview="Stipend ₹25,000 per month for students and freshers.",
                opportunity_type="internship",
            )
        ]
        self.assertEqual(ENGINE._relevance_score(rows, audience=STUDENT), 20.0)

    def test_an_unknown_audience_falls_back_to_student(self) -> None:
        rows = [sample(description_preview="stipend for students", opportunity_type="internship")]
        self.assertEqual(
            ENGINE._relevance_score(rows, audience="nonsense"),
            ENGINE._relevance_score(rows, audience=STUDENT),
        )

    def test_no_samples_scores_zero_rather_than_raising(self) -> None:
        # This runs inside a scoring batch; raising would fail the batch.
        for audience in (STUDENT, FACULTY, INSTITUTION):
            with self.subTest(audience=audience):
                self.assertEqual(ENGINE._relevance_score([], audience=audience), 0)


class TestAccreditedDomainsAreALegitimacySignal(unittest.TestCase):
    """India's registry will not sell an .ac.in or a .gov.in to anyone who asks.

    That makes the suffix a stronger legitimacy signal for an academic source
    than any brand-name list, and it is the signal the old rubric had no way to
    see: icmr.gov.in scored 0 of 15 purely for not being a company.
    """

    def test_government_and_academic_suffixes_are_recognised(self) -> None:
        for domain in ("icmr.gov.in", "iisc.ac.in", "tifr.res.in", "nitttrkol.ac.in"):
            with self.subTest(domain=domain):
                self.assertTrue(
                    any(domain.endswith(s) for s in ENGINE.ACCREDITED_DOMAIN_SUFFIXES),
                    f"{domain} should be recognised as accreditation-controlled",
                )

    def test_an_ordinary_domain_is_not(self) -> None:
        # The signal is worth nothing if anyone can buy it.
        for domain in ("careers.example.com", "jobs-portal.net", "totally-legit-uni.xyz"):
            with self.subTest(domain=domain):
                self.assertFalse(any(domain.endswith(s) for s in ENGINE.ACCREDITED_DOMAIN_SUFFIXES))


class TestCrossValidationCannotPunishBeingFirst(unittest.TestCase):
    def test_the_cold_start_value_is_the_midpoint_not_zero(self) -> None:
        # Cross-validation asks "have we seen a posting like this before". The
        # first source of an audience never has, and scoring it 0 out of 10 for
        # that is circular: the audience can never bootstrap.
        self.assertEqual(ENGINE.COLD_START_CROSS_VALIDATION, 5.0)

    def test_it_is_not_a_free_pass(self) -> None:
        self.assertLess(ENGINE.COLD_START_CROSS_VALIDATION, 10.0)


class TestOpportunityTypeUsesTheAudiencesVocabulary(unittest.TestCase):
    """`"internship" if "intern" in text else "job"` was at five call sites.

    Fine for a student corpus. For the other two it types a call for proposals
    as a job, which then fails that audience's own relevance check downstream
    and drags the source's trust below the promote gate.
    """

    def test_faculty_notices_get_faculty_types(self) -> None:
        cases = [
            ("Faculty Development Programme on Machine Learning", "fdp"),
            ("Advertisement for the post of Associate Professor", "faculty"),
            ("Post-Doctoral Fellowship in Ayurveda Pharmacology", "postdoc"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(_infer_opportunity_type(text, audience=FACULTY), expected)

    def test_institution_notices_get_institution_types(self) -> None:
        cases = [
            ("Call for Proposals under the ATAL Scheme", "proposal"),
            ("Application for NBA Accreditation of UG Programmes", "accreditation"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(_infer_opportunity_type(text, audience=INSTITUTION), expected)

    def test_longer_phrases_win(self) -> None:
        # "faculty development programme" is a course, not a vacancy. Matching
        # "faculty" first would advertise a training course as a job opening.
        self.assertEqual(
            _infer_opportunity_type("Faculty Development Programme", audience=FACULTY), "fdp"
        )

    def test_student_behaviour_is_preserved(self) -> None:
        self.assertEqual(_infer_opportunity_type("Summer Internship 2026", audience=STUDENT), "internship")
        self.assertEqual(_infer_opportunity_type("Backend Developer", audience=STUDENT), "job")

    def test_the_fallback_is_in_the_audiences_own_words(self) -> None:
        # Calling an unrecognised AICTE circular a "Job" is what made every
        # academic row read as a vacancy.
        self.assertNotEqual(_infer_opportunity_type("Notice regarding timetable", audience=INSTITUTION), "job")


if __name__ == "__main__":
    unittest.main()


class TestUnreadableWhoisIsNotYoungDomain(unittest.TestCase):
    """India restricts WHOIS on .gov.in and .ac.in.

    So every government and university source resolved to no creation date and
    landed on the same middling 50 a domain registered last week receives, and
    then on 5 of 10 for reputation. That is not what the check is measuring. A
    registrar only issues one of these suffixes on proof of institutional
    status, which makes the suffix better evidence of establishment than a
    record we are not permitted to read.
    """

    def _service(self):
        from app.services.source_discovery import SourceQualificationService

        return SourceQualificationService()

    def test_an_accredited_suffix_of_unknown_age_scores_as_established(self) -> None:
        result = self._service()._age_unknown("iisc.ac.in")
        self.assertEqual(result.score, 100)
        self.assertIn("accredited_suffix", result.notes)

    def test_an_ordinary_domain_of_unknown_age_stays_neutral(self) -> None:
        # The point is not to be generous. A domain nobody vouches for and whose
        # age we cannot read is genuinely unknown, and must stay that way.
        result = self._service()._age_unknown("careers.example.com")
        self.assertEqual(result.score, 50)
        self.assertNotIn("accredited_suffix", result.notes)

    def test_the_reason_survives_into_the_notes(self) -> None:
        # The notes are what an operator reads when auditing a score. Losing the
        # reason turns "we could not look" into "we looked and found nothing".
        result = self._service()._age_unknown("iitb.ac.in", reason="whois_unavailable")
        self.assertIn("whois_unavailable", result.notes)


class TestReputationAgreesWithQualification(unittest.TestCase):
    """The two checks must not disagree about the same domain.

    Trust reads the qualification notes to score reputation. If qualification
    treats an accredited suffix as established and trust does not, a source is
    credited in one place and charged in the other for the same fact.

    Scored against a stub rather than a DiscoveredSource: the scorer reads two
    attributes, and constructing a Beanie document in a unit test requires an
    initialised collection, which would make this a database test for no gain.
    """

    class _Source:
        def __init__(self, domain: str, notes: str) -> None:
            self.domain = domain
            self.qualification_details = {"domain_age": {"notes": notes}}

    def test_an_accredited_domain_scores_full_reputation_without_an_age(self) -> None:
        source = self._Source("iisc.ac.in", "domain_age_unknown;accredited_suffix")
        self.assertEqual(ENGINE._domain_reputation_score(source), 10)

    def test_an_ordinary_domain_without_an_age_stays_at_five(self) -> None:
        source = self._Source("careers.example.com", "domain_age_unknown")
        self.assertEqual(ENGINE._domain_reputation_score(source), 5)

    def test_a_real_age_still_wins(self) -> None:
        # The suffix rule is a fallback for a record we cannot read, not an
        # override of one we can. A genuinely new .ac.in scores as new.
        source = self._Source("new.ac.in", "age_days=100")
        self.assertEqual(ENGINE._domain_reputation_score(source), 2)
