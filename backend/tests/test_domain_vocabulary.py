"""AYUSH vocabulary for the skill extractor.

The extractor is trained on mainstream tech and business postings. Before this
vocabulary existed it returned [] for AYUSH text - not a weak result, an empty
one. An empty extraction means the domain produces no demand table, which means
a BAMS student is offered either nothing or the software-engineering
questionnaire, while the feature reports on a corpus it never parsed. That is
the failure this repo keeps producing: a confident answer over no data.

The subtle requirement is the last class of tests here. A vocabulary term that
the extractor finds but `normalise_skill` later rejects is worse than one that
was never added - it looks present in the source, costs a review, and is dropped
silently somewhere else entirely.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.domain_vocabulary import (
    AYUSH_VOCABULARY,
    all_vocabulary_terms,
    vocabulary_skill_tags,
)
from app.services.skill_demand import normalise_skill


class TestAyushTextIsNoLongerSilent(unittest.TestCase):
    def test_ayurveda_posting_yields_competencies(self) -> None:
        tags = vocabulary_skill_tags(
            "Ayurveda research associate: Panchakarma, Dravyaguna, "
            "clinical documentation, patient counselling."
        )
        self.assertIn("panchakarma", tags)
        self.assertIn("dravyaguna", tags)

    def test_bams_clinical_posting_yields_competencies(self) -> None:
        tags = vocabulary_skill_tags(
            "BAMS graduate for Kayachikitsa OPD. Knowledge of Charaka Samhita "
            "and Nadi Pariksha required."
        )
        for expected in ("kayachikitsa", "charaka samhita", "nadi pariksha"):
            with self.subTest(term=expected):
                self.assertIn(expected, tags)

    def test_ayush_industry_posting_yields_competencies(self) -> None:
        # The roles that actually employ AYUSH graduates at scale.
        tags = vocabulary_skill_tags(
            "QC chemist for an ayurvedic pharmacy: herbal formulation, "
            "phytochemistry, good manufacturing practice."
        )
        for expected in ("herbal formulation", "phytochemistry", "good manufacturing practice"):
            with self.subTest(term=expected):
                self.assertIn(expected, tags)

    def test_yoga_posting_yields_competencies(self) -> None:
        tags = vocabulary_skill_tags("Yoga therapist: asana, pranayama and diet therapy.")
        self.assertIn("asana", tags)
        self.assertIn("pranayama", tags)


class TestMatchingIsWordBounded(unittest.TestCase):
    """Substring matching would put nonsense in front of students."""

    def test_terms_are_not_matched_inside_other_words(self) -> None:
        # "basti" inside "bastion", "asana" inside "hasana", "hijama" inside a
        # longer token. Each would render as a competency the student lacks.
        for text in ("a bastion of industry", "hasanabad campus", "nasaladvisory"):
            with self.subTest(text=text):
                self.assertEqual(vocabulary_skill_tags(text), [])

    def test_multi_word_terms_need_the_whole_phrase(self) -> None:
        self.assertEqual(vocabulary_skill_tags("we run a samhita reading group"), [])
        self.assertIn("charaka samhita", vocabulary_skill_tags("study of charaka samhita"))

    def test_empty_input_is_empty_output(self) -> None:
        for text in ("", "   ", None):
            with self.subTest(text=text):
                self.assertEqual(vocabulary_skill_tags(text), [])


class TestVocabularySurvivesNormalisation(unittest.TestCase):
    """Every term must survive the filter that demand tables run it through.

    normalise_skill drops anything over three words or forty characters, plus
    sector names and sentence-fragment leads. A vocabulary term caught by one of
    those is dropped after extraction, so it never reaches a questionnaire and
    nothing anywhere reports that it went missing.
    """

    def test_every_term_survives_normalise_skill(self) -> None:
        casualties = [term for term in all_vocabulary_terms() if normalise_skill(term) is None]
        self.assertEqual(
            casualties,
            [],
            f"these terms are extracted but silently filtered out later: {casualties}",
        )

    def test_normalisation_does_not_rewrite_terms(self) -> None:
        # A term that survives but comes back altered would never match the
        # demand table key it was counted under.
        altered = {
            term: normalise_skill(term)
            for term in all_vocabulary_terms()
            if normalise_skill(term) != term
        }
        self.assertEqual(altered, {}, f"terms rewritten by normalisation: {altered}")


class TestVocabularyHygiene(unittest.TestCase):
    def test_no_duplicate_terms(self) -> None:
        terms = list(AYUSH_VOCABULARY)
        duplicates = {term for term in terms if terms.count(term) > 1}
        self.assertEqual(duplicates, set())

    def test_terms_are_lowercase_and_trimmed(self) -> None:
        for term in AYUSH_VOCABULARY:
            with self.subTest(term=term):
                self.assertEqual(term, term.strip().lower())


class TestExistingExtractionIsUnaffected(unittest.TestCase):
    def test_tech_text_gains_no_ayush_terms(self) -> None:
        # The vocabulary is additive; it must not start labelling software
        # postings with clinical competencies.
        self.assertEqual(
            vocabulary_skill_tags(
                "Python backend intern with FastAPI, PostgreSQL and Docker experience."
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
