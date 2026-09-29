"""A city the query parser cannot see is a location filter that never runs.

Ask AI filters by location only when the query parser returns one. The NER model
is general-purpose English and does not carry this corpus's geography: measured
on the live parser, "data science internships in Bangalore" yielded
locations=[] - "Bangalore" was not a place to it, only "Bengaluru" was - and
"Google internships in Hyderabad" put Hyderabad in *companies*.

Neither failure raises anything. The query simply goes out unfiltered, the
shortlist comes from the whole corpus, and the answer reads as though the
constraint had been honoured. That is how a Bangalore question was answered with
roles in neither the field nor the city.

The listing side already had a curated gazetteer for exactly this vocabulary.
These tests pin both halves of the join: the query parser now uses it, and the
terms it matches are the ones the listings are classified by.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.nlp_service import _place_terms_in, _without_places
from app.services.opportunity_placement import PLACE_TERMS


class CompanyFilteringTests(unittest.TestCase):
    """Deterministic, because which names the NER model finds varies by spaCy
    build - a CI runner returned no company for "jobs at Oracle in Pune" while
    the same call locally returned Oracle. What this code owns is which names
    are removed."""

    def test_only_the_place_is_removed(self):
        self.assertEqual(_without_places(["Google", "Hyderabad"], ["Hyderabad"]), ["Google"])

    def test_an_employer_is_never_removed(self):
        self.assertEqual(_without_places(["Oracle"], ["Pune"]), ["Oracle"])

    def test_matching_ignores_case(self):
        self.assertEqual(_without_places(["HYDERABAD"], ["Hyderabad"]), [])

    def test_no_places_means_no_change(self):
        self.assertEqual(_without_places(["Oracle", "Infosys"], []), ["Oracle", "Infosys"])


class GazetteerMatchingTests(unittest.TestCase):
    def test_the_spelling_students_actually_type_is_recognised(self):
        """"Bangalore" outnumbers "Bengaluru" in student phrasing and was the
        exact query that produced the wrong answer."""
        self.assertEqual(_place_terms_in("data science internships in Bangalore"), ["Bangalore"])

    def test_match_keeps_the_caller_s_spelling(self):
        """The value travels back in the response; rewriting the student's own
        word to the gazetteer's entry would read as though we misheard them."""
        self.assertEqual(_place_terms_in("internships in BANGALORE"), ["BANGALORE"])

    def test_multi_word_places_match_whole(self):
        """"New Delhi" must not decompose into "Delhi", which is a different
        filter, and "Tamil Nadu" must not be shadowed by a substring of itself."""
        self.assertEqual(_place_terms_in("internships in New Delhi"), ["New Delhi"])
        self.assertEqual(_place_terms_in("research in Tamil Nadu"), ["Tamil Nadu"])

    def test_a_place_name_inside_a_longer_word_is_not_a_place(self):
        """Substring matching would read "goa" out of "goal" and silently filter
        an unrelated query down to Goa."""
        self.assertEqual(_place_terms_in("my goal is a data role"), [])
        self.assertEqual(_place_terms_in("indiana university programs"), [])

    def test_ordinary_queries_gain_no_location(self):
        """A false positive is worse than a miss: it filters away good rows."""
        for query in ("data analyst roles", "remote ML internships", "summer research programs"):
            self.assertEqual(_place_terms_in(query), [], query)

    def test_two_letter_aliases_are_excluded(self):
        """"la", "sf" and "or" are safe against a listing's location column and
        unsafe against free text, where they are ordinary words."""
        for alias in ("la", "sf", "dc", "or", "ca"):
            self.assertNotIn(alias, PLACE_TERMS)


class EntityRoutingTests(unittest.TestCase):
    """These call the real parser, so they need the spaCy model present."""

    @classmethod
    def setUpClass(cls):
        from app.services.nlp_service import nlp_service

        try:
            nlp_service.extract_entities("warmup")
        except Exception as exc:  # pragma: no cover - environment without the model
            raise unittest.SkipTest(f"spaCy model unavailable: {exc}")
        cls.nlp_service = nlp_service

    def test_a_city_the_model_calls_a_company_is_filed_as_a_location(self):
        """Hyderabad in `companies` is not merely mislabelled - it is applied as
        a company filter, so the query is narrowed by the wrong axis."""
        entities = self.nlp_service.extract_entities("Google internships in Hyderabad")
        self.assertIn("Hyderabad", entities["locations"])
        self.assertNotIn("Hyderabad", entities["companies"])

    def test_a_city_is_not_left_in_companies(self):
        entities = self.nlp_service.extract_entities("jobs at Oracle in Pune")
        self.assertIn("Pune", entities["locations"])
        self.assertNotIn("Pune", entities["companies"])

    def test_the_model_s_own_correct_answers_are_kept(self):
        entities = self.nlp_service.extract_entities("internships in Bengaluru")
        self.assertEqual([value.lower() for value in entities["locations"]], ["bengaluru"])


if __name__ == "__main__":
    unittest.main()
