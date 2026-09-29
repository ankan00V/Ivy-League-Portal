"""The generator's remaining failure is in the adjectives, not the citations.

The ref scheme stopped it inventing opportunities, and the citation gate checks
every id against what was retrieved. Neither touches the sentence a student
actually reads. Live, over a shortlist whose top row was "Internship - Product
Development", the model wrote "Found 2 data science internships in Bangalore" -
every id real, every row retrieved, and the claim false.

Prompt rules did not hold: the instruction to describe the candidates rather
than the query is in the stored template, and the model wrote that sentence
anyway. So the server checks the text. A phrase is reported only when the query
contains it, the summary repeats it, and no retrieved row carries it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.rag import RAGInsights
from app.services.rag_service import RAGService

BANGALORE_ROWS = [
    {
        "title": "Internship - Product Development",
        "description": "Work with the product team in Bangalore",
        "opportunity_type": "Internship",
    },
    {
        "title": "Data Engineering & Analytics Intern",
        "description": "SQL pipelines and dashboards, Bangalore",
        "opportunity_type": "Internship",
    },
]


class ClaimDetectionTests(unittest.TestCase):
    def setUp(self):
        self.service = RAGService()

    def _claims(self, query, summary, rows=None):
        return self.service._unsupported_summary_claims(query, summary, BANGALORE_ROWS if rows is None else rows)

    def test_the_observed_overclaim_is_caught(self):
        claims = self._claims(
            "data science internships in Bangalore",
            "Found 2 data science internships in Bangalore matching Python and SQL skills.",
        )
        self.assertEqual(claims, ["data science"])

    def test_a_claim_is_reported_once_not_as_two_overlapping_bigrams(self):
        """"data science" and "science internships" are the same claim."""
        claims = self._claims(
            "data science internships in Bangalore",
            "Found 2 data science internships in Bangalore.",
        )
        self.assertNotIn("science internships", claims)

    def test_an_accurate_summary_is_left_alone(self):
        claims = self._claims(
            "internships in Bangalore",
            "Six internships in Bangalore across marketing and design.",
        )
        self.assertEqual(claims, [])

    def test_the_plural_a_student_types_matches_the_singular_a_posting_uses(self):
        """Without this the check fires on every correct answer: students ask for
        "internships", postings are titled "Internship"."""
        claims = self._claims(
            "data science internships in Bangalore",
            "Two analytics internships in Bangalore, open to 2027 graduates.",
        )
        self.assertEqual(claims, [])

    def test_supported_terms_are_not_reported(self):
        """"Bangalore" is in the rows, so repeating it is reporting, not claiming."""
        claims = self._claims("internships in Bangalore", "Internships in Bangalore.")
        self.assertNotIn("bangalore", claims)

    def test_framing_words_are_not_claims(self):
        """No posting says "upcoming"; treating that as unsupported would put a
        caveat on answers that are entirely correct."""
        rows = [{"title": "NextGen Hackathon", "description": "a national hackathon"}]
        claims = self._claims("upcoming hackathons", "Found 6 upcoming hackathons.", rows)
        self.assertEqual(claims, [])

    def test_nothing_is_claimed_against_an_empty_shortlist(self):
        """With no rows there is no evidence either way, and the empty-result
        wording already says what happened."""
        self.assertEqual(self._claims("data science in Bangalore", "Nothing matches.", []), [])


class CaveatTests(unittest.TestCase):
    def setUp(self):
        self.service = RAGService()

    def _checked(self, query, summary, rows=BANGALORE_ROWS):
        insights = RAGInsights.model_validate(
            {
                "summary": summary,
                "top_opportunities": [],
                "deadline_urgency": "soon",
                "recommended_action": "apply",
            }
        )
        return self.service._check_summary_against_results(insights, query, rows)

    def test_the_caveat_is_appended_and_the_check_recorded(self):
        checked = self._checked(
            "data science internships in Bangalore",
            "Found 2 data science internships in Bangalore.",
        )
        self.assertIn('None of the listings below mentions "data science".', checked.summary)
        self.assertFalse(checked.safety.hallucination_checks_passed)
        self.assertIn("summary_claim_unsupported:data science", checked.safety.failed_checks)

    def test_the_original_summary_is_kept(self):
        """The accurate half of the sentence is still worth reading; this service
        records a substitution rather than performing one silently."""
        checked = self._checked(
            "data science internships in Bangalore",
            "Found 2 data science internships in Bangalore.",
        )
        self.assertTrue(checked.summary.startswith("Found 2 data science internships in Bangalore."))

    def test_an_accurate_summary_passes_through_untouched(self):
        original = "Six internships in Bangalore across marketing and design."
        checked = self._checked("internships in Bangalore", original)
        self.assertEqual(checked.summary, original)
        self.assertTrue(checked.safety.hallucination_checks_passed)
        self.assertEqual(checked.safety.failed_checks, [])


if __name__ == "__main__":
    unittest.main()
