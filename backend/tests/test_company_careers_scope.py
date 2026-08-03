import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.company_careers_intelligence import _is_early_career


def _row(title: str, description: str = "", tags: list[str] | None = None) -> dict:
    return {"title": title, "description": description, "tags": tags or []}


class TestCompanyCareersEarlyCareerScope(unittest.TestCase):
    """The scope filter previously used plain substring containment.

    `"intern" in haystack` matched "international" and `"campus"` matched
    "Campus Life", so press releases and navigation links were ingested as
    internships. It also searched the description, which meant careers-page
    boilerplate about universities qualified every role on the page.
    """

    def test_substring_lookalikes_are_rejected(self) -> None:
        for title in (
            "L&T Heavy Engineering Wins Orders (Large*) in International Markets",
            "International Trade Analyst",
            "Internal Communications Specialist",
            "Campus Life",
        ):
            with self.subTest(title=title):
                self.assertFalse(_is_early_career(_row(title)))

    def test_description_boilerplate_does_not_qualify_a_role(self) -> None:
        for title, description in (
            ("Business Development Representative", "We hire from top universities."),
            ("Designer Advocate", "Work with students and the community."),
            ("Stock Administrator", "Graduate programme alumni welcome to refer."),
        ):
            with self.subTest(title=title):
                self.assertFalse(_is_early_career(_row(title, description)))

    def test_genuine_early_career_roles_are_kept(self) -> None:
        for title, description in (
            ("Governance, Risk, and Compliance Intern (Fall 2026)", ""),
            ("Software Engineering Intern", "Work alongside senior engineers."),
            ("Graduate Trainee Engineer", "Report to the engineering manager."),
            ("New Grad Software Engineer", ""),
            ("Associate Software Engineer", ""),
            ("Backend Engineer Apprenticeship", ""),
            ("Graduate Programme 2026", ""),
            ("North America Campus Programmes", ""),
            ("Data Analyst Trainee", "Experience: 0-2 years"),
        ):
            with self.subTest(title=title):
                self.assertTrue(_is_early_career(_row(title, description)))

    def test_senior_and_multi_year_roles_are_rejected(self) -> None:
        self.assertFalse(_is_early_career(_row("Senior Software Engineer Intern Program Manager")))
        self.assertFalse(_is_early_career(_row("Data Scientist, Core Data - PhD (2026)")))
        self.assertFalse(
            _is_early_career(_row("Software Engineer", "Requires 5+ years experience."))
        )

    def test_tags_can_carry_the_signal(self) -> None:
        self.assertTrue(_is_early_career(_row("Software Engineer", "", ["internship"])))


if __name__ == "__main__":
    unittest.main()
