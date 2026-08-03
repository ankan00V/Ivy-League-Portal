import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.resume_review_service import review_resume
from app.api.api_v1.endpoints import users


class TestResumeReviewService(unittest.TestCase):
    def test_review_returns_explainable_categories_and_advice(self) -> None:
        review = review_resume(
            """
            Ada Lovelace | ada@example.com | +91 99999 99999 | github.com/ada
            Summary
            Python developer focused on machine learning internships.
            Skills
            Python, SQL, React, Docker, AWS
            Experience
            Built an API that reduced review time by 35% for 2k users.
            Projects
            Developed a recommendation system: https://github.com/ada/recommender
            Education
            B.Tech Computer Science
            """,
            profile_skills="Python, SQL, React",
            preferred_roles="Machine Learning Intern",
        )

        self.assertGreaterEqual(review["score"], 70)
        self.assertEqual(sum(category["maximum"] for category in review["categories"]), 100)
        self.assertTrue(review["advisory"])
        self.assertIn("Contact and links", [category["label"] for category in review["categories"]])

    def test_review_identifies_missing_structure_without_hiring_claims(self) -> None:
        review = review_resume("I enjoy building software and learning every day." * 8)

        self.assertLess(review["score"], 50)
        self.assertIn("Resume structure", review["weaknesses"])
        self.assertTrue(any("skills" in item.lower() for item in review["recommendations"]))
        self.assertIn("does not predict hiring outcomes", review["advisory"])

    def test_review_rejects_unreadably_short_text(self) -> None:
        with self.assertRaises(ValueError):
            review_resume("too short")


class TestResumeReviewEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_review_reads_only_the_authenticated_users_resume(self) -> None:
        profile = SimpleNamespace(
            account_type="candidate",
            resume_storage_key="resume.txt",
            resume_filename="resume.txt",
            skills="Python, SQL",
            preferred_roles="Data Analyst Intern",
        )
        content = (
            "Candidate candidate@example.com +91 99999 99999\n"
            "Skills\nPython SQL\nProjects\nBuilt a data dashboard that improved reporting by 40%.\n"
            "Education\nB.Tech\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "resume.txt").write_text(content, encoding="utf-8")
            with (
                patch.object(users, "_get_or_create_profile_for_user", new=AsyncMock(return_value=profile)),
                patch.object(users, "_resume_storage_dir", return_value=Path(tmpdir)),
            ):
                response = await users.get_resume_review(current_user=SimpleNamespace(id="user-id"))

        self.assertEqual(response.resume_filename, "resume.txt")
        self.assertGreater(response.score, 0)
        self.assertIn("does not predict hiring outcomes", response.advisory)


if __name__ == "__main__":
    unittest.main()
