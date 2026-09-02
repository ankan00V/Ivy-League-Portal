"""Recruitment paperwork is not an opportunity.

Academic and government recruitment pages interleave openings with the residue
of past ones - admit cards, merit lists, results, provisional eligibility lists.
They sit in the same list, in the same markup, often the same wording minus one
noun, so extraction cannot tell them apart by shape.

Measured on IISc, the first faculty source to produce anything: twelve candidate
rows, of which three were real (a postdoctoral programme, an instructor post, a
faculty recruitment drive) and the rest were admit cards, merit lists and
results.

Showing someone "Third Revised Merit List" in a feed of opportunities is worse
than showing them nothing. They cannot apply to it, and it teaches them the feed
is not worth reading - which costs every genuine listing behind it.

The filter has to cut precisely. Half these titles contain the word
"recruitment", so a rule keyed on that would take the real openings with the
paperwork.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.source_discovery import is_process_notice


class TestPaperworkIsRejected(unittest.TestCase):
    def test_real_titles_from_the_live_corpus_are_rejected(self) -> None:
        # Verbatim from IISc's recruitment page.
        for title in (
            "Recruitment for the position of Assistant Registrar – Admit Card for Written Exam",
            "Deputy Registrar – Admit Card for Written Exam",
            "Third Revised Merit List – Technical Assistant Recruitment",
            "Result of the recruitment for the post of Assistant Registrar and Admin Officer",
            "Provisional List of Eligible and Not Eligible candidates – Assistant Engineer",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_process_notice(title), title)

    def test_other_paperwork_shapes_are_rejected(self) -> None:
        for title in (
            "Answer Key for the written examination",
            "Corrigendum to Advertisement No. 12/2026",
            "Interview Schedule for shortlisted candidates",
            "Final Selection List for Junior Assistant",
            "Cut-off marks for the screening test",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_process_notice(title))


class TestRealOpeningsSurvive(unittest.TestCase):
    """The precision half. Most of these contain "recruitment" too."""

    def test_real_titles_from_the_live_corpus_are_kept(self) -> None:
        for title in (
            "Postdoctoral Fellowship Programmes",
            "Recruitment for the position of Instructor for MSc Chemical Sciences Programme",
            "Special Recruitment Drive for SC/ST/OBC-NCL/EWS/PWD categories for Faculty",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_process_notice(title), title)

    def test_ordinary_openings_are_kept(self) -> None:
        for title in (
            "Assistant Professor - Department of Ayurveda",
            "Faculty Development Programme on Machine Learning",
            "Software Engineering Intern",
            "Research Associate, Panchakarma",
            "Applications are invited for the post of Lecturer",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_process_notice(title))

    def test_empty_input_is_not_a_notice(self) -> None:
        # A row with no title is dropped by the title check, not by this one;
        # returning True here would blame the wrong filter in the logs.
        for title in ("", "   ", None):
            with self.subTest(title=title):
                self.assertFalse(is_process_notice(title))

    def test_matching_ignores_case_and_spacing(self) -> None:
        self.assertTrue(is_process_notice("ADMIT   CARD for written exam"))


class TestNavigationLabelsAreRejected(unittest.TestCase):
    """A page's own navigation extracts identically to its listings.

    "Announcements" came out of IISc's recruitment page alongside the real
    postdoctoral and instructor openings, because the section headings sit in the
    same markup as the vacancies filed under them. A feed of opportunities whose
    first row is "Announcements" tells a reader immediately that nobody looked.
    """

    def test_section_headings_are_rejected(self) -> None:
        from app.services.source_discovery import is_navigation_label

        for title in (
            "Announcements",
            "Careers",
            "Current Openings",
            "Notices",
            "View all",
            "Contract/Project Staff",
            "Tenders",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_navigation_label(title), title)

    def test_a_category_name_inside_a_real_title_is_kept(self) -> None:
        # The distinction the whole-title match exists for: "Faculty positions"
        # is a heading, "Special Recruitment Drive ... for Faculty positions" is
        # an opening. A substring rule would take both.
        from app.services.source_discovery import is_navigation_label

        for title in (
            "Special Recruitment Drive for SC/ST/OBC-NCL/EWS/PWD categories for Faculty positions",
            "Recruitment for the position of Instructor for MSc Chemical Sciences Programme",
            "Postdoctoral Fellowship Programmes",
            "Appointment of Director of Indian Institute of Science Education & Research",
            "Assistant Professor - Department of Ayurveda",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_navigation_label(title), title)

    def test_empty_input_is_not_a_label(self) -> None:
        from app.services.source_discovery import is_navigation_label

        for title in ("", "   ", None):
            with self.subTest(title=title):
                self.assertFalse(is_navigation_label(title))

    def test_trailing_punctuation_and_case_do_not_hide_a_label(self) -> None:
        from app.services.source_discovery import is_navigation_label

        self.assertTrue(is_navigation_label("  ANNOUNCEMENTS:  "))


if __name__ == "__main__":
    unittest.main()
