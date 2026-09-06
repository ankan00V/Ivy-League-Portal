"""Skill assessment: demand derivation, corroboration, gap ranking.

Everything here ends up as advice shown to a student - "you are missing Docker",
"you are ready for this domain" - which is the worst possible place for a quiet
wrong answer. A bad skill list does not look like a bug; it looks like the
feature working, with an authoritative tone.

Two properties carry most of the weight:

Junk must not become advice. The skill extractor is recall-oriented and returns
sentence fragments and sector names alongside real skills. Before the filters
below, the AI domain's top "skills" were health care, journalism, retail,
hospitality and sports - none of which are things a student can go and learn.

Self-ratings must be corroborated. A self-assessment measures confidence, not
competence, and treating the two as equal is what makes these features useless.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.skill_assessment_service import (
    CLAIM_THRESHOLD,
    UNSUPPORTED_CEILING,
    analyse,
    build_questionnaire,
    corroborate,
)
from app.services.skill_demand import domain_key, normalise_skill, rank_demand


def _profile(**kwargs):
    base = dict(
        skills=None,
        interests=None,
        interest_graph=[],
        project_entries=[],
        certification_entries=[],
        experience_entries=[],
        education_entries=[],
        honor_entries=[],
        volunteer_entries=[],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestSkillNormalisation(unittest.TestCase):
    def test_real_skills_survive(self) -> None:
        for raw, expected in (
            ("Python", "python"),
            ("  SQL  ", "sql"),
            ("Microsoft Excel", "microsoft excel"),
            ("machine learning", "machine learning"),
            ("clinical care.", "clinical care"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalise_skill(raw), expected)

    def test_sentence_fragments_are_rejected(self) -> None:
        # These come straight out of the extractor on real postings.
        for raw in (
            "identify the customer s unique needs",
            "create safe environments",
            "ability to work under pressure",
            "responsible for the team",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(normalise_skill(raw))

    def test_sector_names_are_rejected(self) -> None:
        # The specific regression: postings name the industry they serve, and
        # those terms outranked real skills in the AI domain.
        for raw in ("health care", "journalism", "retail", "hospitality", "finance"):
            with self.subTest(raw=raw):
                self.assertIsNone(normalise_skill(raw))

    def test_soft_skill_phrases_are_kept_despite_length(self) -> None:
        self.assertEqual(normalise_skill("attention to detail"), "attention to detail")

    def test_junk_is_rejected(self) -> None:
        for raw in ("", "  ", "a", "123", "-", "x" * 60):
            with self.subTest(raw=raw):
                self.assertIsNone(normalise_skill(raw))


class TestDemandRanking(unittest.TestCase):
    def test_share_is_per_posting_not_per_mention(self) -> None:
        # A description repeating "python" six times is one employer asking for
        # python, not six. Counting mentions would let one verbose posting
        # dominate a domain.
        postings = [["python", "python", "python"], ["sql"], ["python"]]
        ranked = rank_demand(postings, min_postings=1)
        by_skill = {row.skill: row for row in ranked}
        self.assertEqual(by_skill["python"].postings, 2)
        self.assertAlmostEqual(by_skill["python"].share, 2 / 3, places=3)

    def test_rare_skills_are_dropped(self) -> None:
        postings = [["python"], ["python"], ["python"], ["cobol"]]
        ranked = rank_demand(postings, min_postings=3)
        self.assertEqual([row.skill for row in ranked], ["python"])

    def test_junk_never_reaches_the_table(self) -> None:
        postings = [["python", "health care", "identify the customer s needs"]] * 5
        ranked = rank_demand(postings, min_postings=1)
        self.assertEqual([row.skill for row in ranked], ["python"])

    def test_empty_input_is_empty_output(self) -> None:
        self.assertEqual(rank_demand([]), [])


class TestQuestionnaire(unittest.TestCase):
    def _rows(self):
        rows = [
            {"skill": f"tech{i}", "postings": 50 - i, "share": 0.5 - i / 100, "is_soft": False}
            for i in range(20)
        ]
        rows.append({"skill": "communication", "postings": 5, "share": 0.05, "is_soft": True})
        return rows

    def test_soft_skills_get_their_own_quota(self) -> None:
        # Soft skills are named in far fewer postings, so a single ranked list
        # buries them entirely - and the problem statement asks for both.
        items = build_questionnaire(self._rows(), max_technical=5, max_soft=3)
        self.assertTrue(any(item.is_soft for item in items))
        self.assertEqual(sum(1 for item in items if not item.is_soft), 5)

    def test_questions_carry_their_evidence(self) -> None:
        items = build_questionnaire(self._rows(), max_technical=1, max_soft=0)
        self.assertIn("live posting", items[0].rationale)


class TestCorroboration(unittest.TestCase):
    def test_unsupported_claim_is_pulled_down_and_reported(self) -> None:
        adjusted, adjustments = corroborate({"docker": 4}, profile=_profile())
        self.assertEqual(adjusted["docker"], UNSUPPORTED_CEILING)
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["claimed"], 4)

    def test_claim_backed_by_a_project_is_kept(self) -> None:
        profile = _profile(project_entries=[{"name": "Ranker", "skills": ["docker"]}])
        adjusted, adjustments = corroborate({"docker": 4}, profile=profile)
        self.assertEqual(adjusted["docker"], 4)
        self.assertEqual(adjustments, [])

    def test_low_ratings_are_never_adjusted(self) -> None:
        # Nothing needs backing to say "I cannot do this".
        adjusted, adjustments = corroborate({"docker": 1}, profile=_profile())
        self.assertEqual(adjusted["docker"], 1)
        self.assertEqual(adjustments, [])

    def test_soft_skills_accept_activity_as_evidence(self) -> None:
        # Nobody lists "communication" among a project's skills. Requiring a
        # name match marks every student weak at every soft skill, which turns
        # the advice into "work on teamwork" for the entire cohort.
        profile = _profile(volunteer_entries=[{"organization": "NSS", "role": "Coordinator"}])
        adjusted, adjustments = corroborate({"communication": 4}, profile=profile)
        self.assertEqual(adjusted["communication"], 4)
        self.assertEqual(adjustments, [])

    def test_soft_skill_with_no_activity_at_all_is_still_adjusted(self) -> None:
        adjusted, _ = corroborate({"communication": 4}, profile=_profile())
        self.assertEqual(adjusted["communication"], UNSUPPORTED_CEILING)

    def test_levels_outside_the_scale_are_clamped(self) -> None:
        adjusted, _ = corroborate({"python": 99, "sql": -5}, profile=_profile())
        self.assertLessEqual(adjusted["python"], 4)
        self.assertGreaterEqual(adjusted["sql"], 0)


class TestGapAnalysis(unittest.TestCase):
    DEMAND = [
        {"skill": "python", "postings": 54, "share": 0.40, "is_soft": False},
        {"skill": "docker", "postings": 8, "share": 0.05, "is_soft": False},
    ]

    def test_gaps_rank_by_demand_not_by_deficit_alone(self) -> None:
        # Equally weak at both, but being weak at what the market asks for is
        # the gap worth a student's semester.
        result = analyse(
            domain="Engineering",
            responses={"python": 1, "docker": 1},
            demand_rows=self.DEMAND,
            profile=_profile(),
        )
        self.assertEqual([gap.skill for gap in result.gaps], ["python", "docker"])

    def test_unanswered_skills_count_as_absent(self) -> None:
        # A skill the student skipped is a gap, not a neutral. Treating silence
        # as competence would inflate every readiness score.
        result = analyse(
            domain="Engineering", responses={"python": 4}, demand_rows=self.DEMAND, profile=_profile()
        )
        self.assertIn("docker", [gap.skill for gap in result.gaps])

    def test_readiness_is_demand_weighted(self) -> None:
        strong_where_it_counts = analyse(
            domain="E",
            responses={"python": 4, "docker": 0},
            demand_rows=self.DEMAND,
            profile=_profile(project_entries=[{"name": "p", "skills": ["python"]}]),
        )
        strong_where_it_does_not = analyse(
            domain="E",
            responses={"python": 0, "docker": 4},
            demand_rows=self.DEMAND,
            profile=_profile(project_entries=[{"name": "p", "skills": ["docker"]}]),
        )
        self.assertGreater(
            strong_where_it_counts.readiness_score,
            strong_where_it_does_not.readiness_score,
        )

    def test_readiness_stays_within_bounds(self) -> None:
        for responses in ({}, {"python": 4, "docker": 4}, {"python": 0, "docker": 0}):
            with self.subTest(responses=responses):
                result = analyse(
                    domain="E",
                    responses=responses,
                    demand_rows=self.DEMAND,
                    profile=_profile(),
                )
                self.assertGreaterEqual(result.readiness_score, 0.0)
                self.assertLessEqual(result.readiness_score, 100.0)

    def test_adjusted_claims_are_flagged_in_the_output(self) -> None:
        # The student must be able to see that their answer was overridden.
        result = analyse(
            domain="E",
            responses={"python": 4},
            demand_rows=self.DEMAND,
            profile=_profile(),
        )
        self.assertTrue(result.adjustments)
        python_rows = [row for row in result.gaps + result.strengths if row.skill == "python"]
        self.assertTrue(python_rows)
        self.assertFalse(python_rows[0].corroborated)

    def test_corroborated_strength_is_reported_as_a_strength(self) -> None:
        result = analyse(
            domain="E",
            responses={"python": 4},
            demand_rows=self.DEMAND,
            profile=_profile(project_entries=[{"name": "p", "skills": ["python"]}]),
        )
        self.assertIn("python", [row.skill for row in result.strengths])
        self.assertGreaterEqual(result.corroborated["python"], CLAIM_THRESHOLD)


class TestDomainMatching(unittest.TestCase):
    """Profiles and the corpus disagree on casing; lookups must not.

    Profiles store "AI AND MACHINE LEARNING"; opportunities store "AI and
    Machine Learning". Matching the display values found nothing, so every
    student fell through to the whole-market table while the UI told them their
    domain had too few postings. It looked exactly like the feature working.
    """

    def test_profile_casing_matches_corpus_casing(self) -> None:
        self.assertEqual(
            domain_key("AI AND MACHINE LEARNING"),
            domain_key("AI and Machine Learning"),
        )

    def test_whitespace_does_not_break_matching(self) -> None:
        self.assertEqual(domain_key("  Data   Science "), domain_key("Data Science"))

    def test_distinct_domains_stay_distinct(self) -> None:
        self.assertNotEqual(domain_key("Engineering"), domain_key("Data Science"))

    def test_blank_domain_is_empty_not_a_match_for_everything(self) -> None:
        self.assertEqual(domain_key(None), "")
        self.assertEqual(domain_key("   "), "")


class TestPersonalTraitsAreNotSkills(unittest.TestCase):
    """A student must never be told they have a gap in "motivated".

    Job adverts are full of personal qualities and the extractor returns them as
    confidently as it returns "python". A real assessment against the live
    corpus produced gaps including motivated, talented, dependable, enthusiastic
    and professional - none of which can be acted on, and all of which are the
    first thing a reader notices.
    """

    def test_personal_qualities_are_rejected(self) -> None:
        for trait in (
            "motivated",
            "talented",
            "dependable",
            "enthusiastic",
            "professional",
            "creative",
            "tech-savvy",
            "passionate",
        ):
            with self.subTest(trait=trait):
                self.assertIsNone(normalise_skill(trait))

    def test_qualifications_are_rejected(self) -> None:
        # A degree is not something a student closes a gap on this semester.
        for term in ("mba", "btech", "phd", "bams", "diploma", "graduate"):
            with self.subTest(term=term):
                self.assertIsNone(normalise_skill(term))

    def test_bare_generic_nouns_are_rejected(self) -> None:
        for term in ("quality", "support", "execution", "errors", "learn", "tools"):
            with self.subTest(term=term):
                self.assertIsNone(normalise_skill(term))

    def test_real_skills_are_not_caught_by_these_filters(self) -> None:
        # The filters must not take the neighbouring genuine competency with
        # them: "quality" goes, "quality control" stays.
        for skill in (
            "quality control",
            "analytical thinking",
            "problem solving",
            "communication",
            "machine learning",
            "microsoft excel",
            "panchakarma",
        ):
            with self.subTest(skill=skill):
                self.assertEqual(normalise_skill(skill), skill)


if __name__ == "__main__":
    unittest.main()
