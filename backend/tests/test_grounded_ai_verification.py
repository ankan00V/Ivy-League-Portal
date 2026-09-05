"""The check that decides whether a number a user acts on came from the database.

A recruiter reading "18% of candidates can evidence Kubernetes" will change a
requirement on the strength of it. If the model invented that figure, the
platform has done something worse than being unhelpful - it has laundered a
guess into a measurement, wearing the same typography as the measured rows
directly above it.

So the verifier is the load-bearing part of every AI feature here, and these
tests pin the three ways it could quietly stop working: passing an invented
number, rejecting a real one, and being walked around by a percentage written
in the other unit.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.grounded_ai import (
    GroundedAnswer,
    collect_supported_numbers,
    live_model,
    unsupported_numbers,
)

FACTS = {
    "candidates_assessed": 6,
    "skills": [
        {"skill": "machine learning", "demand_share": 0.041, "supply": 0.0},
        {"skill": "python", "demand_share": 0.044, "supply": 0.6667},
    ],
}


class TestSupportedNumbers(unittest.TestCase):
    def test_a_share_is_supported_in_both_units(self) -> None:
        # Services store shares as 0..1 and every surface renders them as
        # 0..100. A model shown 0.041 and writing "4.1%" is quoting the fact it
        # was given, and rejecting that would make the verifier unusable.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("demand is 4.1%", supported), [])
        self.assertEqual(unsupported_numbers("demand is 0.041", supported), [])

    def test_counts_are_supported(self) -> None:
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("6 candidates were assessed", supported), [])

    def test_nested_values_are_found(self) -> None:
        # The facts are nested dicts of lists. A walker that only looked at the
        # top level would reject every real number in the payload.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("supply is 66.7%", supported), [])


class TestInventedNumbersAreCaught(unittest.TestCase):
    """The failure this whole module exists to prevent."""

    def test_a_percentage_not_in_the_facts_is_rejected(self) -> None:
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("demand is 18%", supported), ["18"])

    def test_an_invented_salary_is_rejected(self) -> None:
        supported = collect_supported_numbers(FACTS)
        self.assertIn("12", unsupported_numbers("salaries average 12 lakh", supported))

    def test_a_plausible_neighbour_is_still_rejected(self) -> None:
        # 14.1 must not be accepted because 4.1 is supported. A tolerance wide
        # enough to collapse those would defeat the check entirely.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("demand is 14.1%", supported), ["14.1"])


class TestExemptions(unittest.TestCase):
    def test_a_year_is_not_a_claim_about_the_data(self) -> None:
        # "by 2027" is a date. Treating it as an unsupported statistic rejected
        # otherwise-correct answers for saying when to act.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("Plan for the 2027 intake.", supported), [])

    def test_small_enumerating_counts_are_allowed(self) -> None:
        # "three things stand out" is the model counting its own points, not
        # quoting the data.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("There are 3 things to fix.", supported), [])

    def test_a_year_shaped_decimal_is_not_exempt(self) -> None:
        # 2027.5 is not a year, and the exemption must not become a hole a
        # decimal can be pushed through.
        supported = collect_supported_numbers(FACTS)
        self.assertEqual(unsupported_numbers("the figure is 2027.5", supported), ["2027.5"])


class TestRetiredModelGuard(unittest.TestCase):
    """A withdrawn model must not be able to silently disable a feature.

    Every LLM path here catches provider errors and serves a deterministic
    answer, which is right for a timeout and exactly wrong for an HTTP 410: the
    product keeps returning well-formed answers and nothing on screen says the
    model was never consulted. That is how Ask AI ran from 2026-08-26 without
    anyone noticing.
    """

    def test_a_retired_model_is_replaced(self) -> None:
        chosen = live_model(
            "meta/llama-3.1-8b-instruct", fallback="live/model", context="test"
        )
        self.assertEqual(chosen, "live/model")

    def test_a_live_model_is_left_alone(self) -> None:
        chosen = live_model("some/live-model", fallback="live/model", context="test")
        self.assertEqual(chosen, "some/live-model")

    def test_an_empty_setting_falls_back(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(live_model(value, fallback="live/model", context="t"), "live/model")


class TestAnswerShape(unittest.TestCase):
    def test_source_is_always_reported(self) -> None:
        # The caller renders this. A briefing that cannot say whether a model or
        # a template wrote it asks the reader to trust it blindly.
        answer = GroundedAnswer(headline="h", paragraphs=["p"])
        self.assertIn(answer.to_dict()["source"], {"llm", "deterministic", "refused"})


if __name__ == "__main__":
    unittest.main()


class TestCollectionLengthsAreFacts(unittest.TestCase):
    """A model counting what it was handed is not inventing anything.

    Rejecting "you have 6 gaps" when six gap rows were passed in is the false
    rejection that makes a verifier look like a nuisance instead of a
    safeguard - and every false rejection pushes a real reading off the page in
    favour of a template.
    """

    def test_a_list_length_is_supported(self) -> None:
        facts = {"gaps": [{"skill": "a"}] * 6}
        self.assertEqual(unsupported_numbers("You have 6 gaps.", collect_supported_numbers(facts)), [])

    def test_a_number_that_is_not_a_length_is_still_caught(self) -> None:
        facts = {"gaps": [{"skill": "a"}] * 6}
        self.assertEqual(unsupported_numbers("You have 41 gaps.", collect_supported_numbers(facts)), ["41"])


class TestBriefingCache(unittest.TestCase):
    """Keyed on content, so it can never serve a reading of numbers that moved.

    These panels were adding 8 to 21 seconds to the endpoints rendering them,
    and what they narrate barely changes. A time-based cache would have to
    choose between stale readings and pointless regeneration; a content key has
    neither problem - if any number changes, the key changes with it.
    """

    def _narrator(self):
        from app.services.grounded_ai import GroundedNarrator

        return GroundedNarrator()

    def test_identical_facts_share_a_key(self) -> None:
        n = self._narrator()
        facts = {"skills": [{"skill": "python", "supply": 0.66}]}
        self.assertEqual(n._cache_key("p", facts), n._cache_key("p", dict(facts)))

    def test_key_order_does_not_matter(self) -> None:
        n = self._narrator()
        self.assertEqual(n._cache_key("p", {"a": 1, "b": 2}), n._cache_key("p", {"b": 2, "a": 1}))

    def test_a_changed_number_changes_the_key(self) -> None:
        # The property the whole design rests on. If this ever stopped holding,
        # a dashboard would show a paragraph about figures no longer on it.
        n = self._narrator()
        before = n._cache_key("p", {"skills": [{"supply": 0.66}]})
        after = n._cache_key("p", {"skills": [{"supply": 0.67}]})
        self.assertNotEqual(before, after)

    def test_two_audiences_reading_the_same_facts_do_not_collide(self) -> None:
        # The same rows read for a recruiter and for a registrar are different
        # readings. Keying on facts alone would serve one to the other.
        n = self._narrator()
        facts = {"skills": [{"supply": 0.66}]}
        self.assertNotEqual(n._cache_key("recruiter prompt", facts), n._cache_key("registrar prompt", facts))

    def test_the_cache_is_bounded(self) -> None:
        n = self._narrator()
        for index in range(n._cache_limit + 25):
            n._remember(f"key-{index}", GroundedAnswer(headline="h", paragraphs=["p"]))
        self.assertLessEqual(len(n._cache), n._cache_limit)

    def test_the_oldest_entry_is_evicted_first(self) -> None:
        n = self._narrator()
        n._cache_limit = 3
        for index in range(4):
            n._remember(f"key-{index}", GroundedAnswer(headline=str(index), paragraphs=["p"]))
        self.assertNotIn("key-0", n._cache)
        self.assertIn("key-3", n._cache)
