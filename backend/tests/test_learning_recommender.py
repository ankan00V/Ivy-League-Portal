"""Matching learning programmes to a student's skill gaps.

This is the last step of the loop the problem statement describes - assessment,
gap, then a programme that closes it - and it is the step where a plausible
implementation gives bad advice without failing.

Ranking by how many skills a programme lists always favours whichever provider
claims the most, so a student following the list spends a semester on the
broadest advert rather than their largest gap. Ranking by the value of the gaps
closed is the whole point, and the two orderings look identical until you check.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.learning_recommender import recommend_programs


def _program(pid: str, title: str, skills, **kwargs):
    base = dict(
        id=pid,
        title=title,
        provider="Provider",
        url=None,
        program_format="course",
        duration_weeks=4,
        is_free=True,
        certificate_offered=False,
        skills_taught=skills,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


GAPS = [
    {"skill": "python", "priority": 1.2},
    {"skill": "docker", "priority": 0.1},
    {"skill": "sql", "priority": 0.4},
]


class TestRankingIsByValueNotBreadth(unittest.TestCase):
    def test_one_big_gap_beats_many_small_ones(self) -> None:
        # The regression this file exists for. The broad programme lists three
        # skills; the focused one closes the gap that actually matters.
        broad = _program("p1", "Everything Bootcamp", ["docker", "git", "excel"])
        focused = _program("p2", "Python for Backend", ["python"])
        ranked = recommend_programs(gaps=GAPS, programs=[broad, focused])
        self.assertEqual(ranked[0].program_id, "p2")

    def test_score_sums_the_gaps_closed(self) -> None:
        combined = _program("p3", "Python and SQL", ["python", "sql"])
        ranked = recommend_programs(gaps=GAPS, programs=[combined])
        self.assertAlmostEqual(ranked[0].score, 1.6, places=6)

    def test_gaps_are_reported_most_valuable_first(self) -> None:
        combined = _program("p3", "Python and SQL", ["sql", "python"])
        ranked = recommend_programs(gaps=GAPS, programs=[combined])
        self.assertEqual(ranked[0].closes_gaps, ["python", "sql"])

    def test_skills_the_student_does_not_lack_add_nothing(self) -> None:
        # Teaching something already mastered is not worth ranking a programme up.
        padded = _program("p4", "Python plus filler", ["python", "kubernetes", "rust"])
        plain = _program("p5", "Python only", ["python"])
        ranked = recommend_programs(gaps=GAPS, programs=[padded, plain])
        self.assertEqual(ranked[0].score, ranked[1].score)


class TestIrrelevantProgrammesAreDropped(unittest.TestCase):
    def test_programme_closing_nothing_is_excluded(self) -> None:
        # Not ranked last - excluded. A list padded with irrelevant entries
        # teaches the student that the list is not worth reading.
        irrelevant = _program("p6", "Advanced Welding", ["welding"])
        ranked = recommend_programs(gaps=GAPS, programs=[irrelevant])
        self.assertEqual(ranked, [])

    def test_no_gaps_means_no_recommendations(self) -> None:
        self.assertEqual(recommend_programs(gaps=[], programs=[_program("p7", "X", ["python"])]), [])

    def test_no_programmes_means_no_recommendations(self) -> None:
        self.assertEqual(recommend_programs(gaps=GAPS, programs=[]), [])

    def test_programme_with_no_skills_is_excluded(self) -> None:
        self.assertEqual(recommend_programs(gaps=GAPS, programs=[_program("p8", "Vague", [])]), [])


class TestNormalisationAndTies(unittest.TestCase):
    def test_matching_ignores_case_and_spacing(self) -> None:
        program = _program("p9", "ML", ["  Machine   Learning "])
        ranked = recommend_programs(
            gaps=[{"skill": "machine learning", "priority": 0.9}], programs=[program]
        )
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].closes_gaps, ["machine learning"])

    def test_duplicate_gap_entries_do_not_double_count(self) -> None:
        gaps = [{"skill": "python", "priority": 1.0}, {"skill": "python", "priority": 1.0}]
        ranked = recommend_programs(gaps=gaps, programs=[_program("p10", "Py", ["python"])])
        self.assertAlmostEqual(ranked[0].score, 1.0, places=6)

    def test_free_wins_a_tie(self) -> None:
        paid = _program("paid", "Paid Python", ["python"], is_free=False)
        free = _program("free", "Free Python", ["python"], is_free=True)
        ranked = recommend_programs(gaps=GAPS, programs=[paid, free])
        self.assertEqual(ranked[0].program_id, "free")

    def test_shorter_wins_a_tie_between_free_programmes(self) -> None:
        long_one = _program("long", "Long Python", ["python"], duration_weeks=52)
        short_one = _program("short", "Short Python", ["python"], duration_weeks=2)
        ranked = recommend_programs(gaps=GAPS, programs=[long_one, short_one])
        self.assertEqual(ranked[0].program_id, "short")

    def test_missing_duration_does_not_win_the_tie(self) -> None:
        # An unspecified duration must not be treated as zero weeks.
        unknown = _program("unknown", "Unknown Python", ["python"], duration_weeks=None)
        known = _program("known", "Known Python", ["python"], duration_weeks=3)
        ranked = recommend_programs(gaps=GAPS, programs=[unknown, known])
        self.assertEqual(ranked[0].program_id, "known")

    def test_malformed_priority_does_not_crash_the_list(self) -> None:
        gaps = [{"skill": "python", "priority": "not a number"}, {"skill": "sql", "priority": 0.4}]
        ranked = recommend_programs(gaps=gaps, programs=[_program("p11", "SQL", ["sql"])])
        self.assertEqual(len(ranked), 1)

    def test_limit_is_respected(self) -> None:
        programs = [_program(f"p{i}", f"Python {i}", ["python"]) for i in range(20)]
        self.assertEqual(len(recommend_programs(gaps=GAPS, programs=programs, limit=5)), 5)


if __name__ == "__main__":
    unittest.main()
