"""A website's own menu must not become opportunities.

IIT Bombay's careers page promoted 73 rows through every gate this pipeline
has. They were titled "Placements", "Donate", "CSR", "Institute magazines",
"Institute Vision & Mission" and "Director's Message". Not one was an opening.

The listing selector these templates fall back to is
`[data-job-id], .job, .opening, article, li`, and on a site with no job markup
the only thing that matches is every `<li>` on the page - the menu. A feed of a
university's navigation is worse than an empty feed: an empty one says "nothing
yet", and that one says "apply to Donate".

Two filters ship, and a third was measured and rejected. The rejection is
tested too, because "strip the nav first" is the obvious idea and the next
person to have it should find the numbers rather than the intuition.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.audiences import FACULTY, INSTITUTION, STUDENT
from app.services.source_discovery import is_self_link, looks_like_opportunity

#: Verbatim from the rows IIT Bombay promoted.
REAL_MENU_ITEMS = [
    "Placements",
    "Student wellness center",
    "Donate",
    "CSR",
    "Institute magazines",
    "Institute Vision & Mission",
    "Director’s Message",
    "Books & Videos",
    "Digital Photo Archive",
    "Vendors",
    "Kshitij",
    "Organization",
]


class TestTheRowsThatGotThrough(unittest.TestCase):
    def test_every_promoted_menu_item_is_now_rejected(self) -> None:
        for title in REAL_MENU_ITEMS:
            with self.subTest(title=title):
                self.assertFalse(
                    looks_like_opportunity(title, audience=FACULTY),
                    f"{title!r} reached the faculty feed once and must not again",
                )


class TestRealPostingsSurvive(unittest.TestCase):
    """The filter is worthless if it also removes the thing it protects."""

    def test_faculty_postings_pass(self) -> None:
        for title in [
            "Advertisement for the post of Assistant Professor in Computer Science",
            "Applications invited for Post-Doctoral Fellowship in Ayurveda",
            "Faculty Development Programme on Machine Learning, apply by 30 September",
            "Walk-in interview for Research Associate",
        ]:
            with self.subTest(title=title):
                self.assertTrue(looks_like_opportunity(title, audience=FACULTY))

    def test_institution_notices_pass(self) -> None:
        for title in [
            "Call for Proposals under the Institutional Development Scheme",
            "Circular regarding accreditation of UG programmes",
            "Notification: empanelment of institutions for the collaboration grant",
        ]:
            with self.subTest(title=title):
                self.assertTrue(looks_like_opportunity(title, audience=INSTITUTION))

    def test_student_postings_pass(self) -> None:
        # The student corpus is 2,222 live rows and the only feed that has ever
        # worked. This filter must be free for it.
        for title in [
            "Software Engineering Internship, Bengaluru - apply now",
            "Backend Developer job at a fintech startup",
            "Graduate Engineer Trainee opening",
        ]:
            with self.subTest(title=title):
                self.assertTrue(looks_like_opportunity(title, audience=STUDENT))


class TestAudienceVocabulariesDoNotLeak(unittest.TestCase):
    def test_a_menu_item_is_not_rescued_by_another_audience(self) -> None:
        for title in ("Donate", "Director’s Message", "Digital Photo Archive"):
            for audience in (STUDENT, FACULTY, INSTITUTION):
                with self.subTest(title=title, audience=audience):
                    self.assertFalse(looks_like_opportunity(title, audience=audience))

    def test_an_unknown_audience_falls_back_to_student(self) -> None:
        self.assertEqual(
            looks_like_opportunity("Internship opening", audience="nonsense"),
            looks_like_opportunity("Internship opening", audience=STUDENT),
        )


class TestSelfLinksAreNavigation(unittest.TestCase):
    """What the vocabulary gate honestly cannot catch.

    "Faculty Recruitment" on a recruitment landing page contains "faculty" and
    "recruit" and is still not an opening - it is the page linking to itself.
    A posting has somewhere of its own to send you.
    """

    PAGE = "https://www.iitb.ac.in/career/apply"

    def test_a_link_to_the_same_page_is_rejected(self) -> None:
        for url in (
            "https://www.iitb.ac.in/career/apply",
            "https://www.iitb.ac.in/career/apply/",
            "https://www.iitb.ac.in/career/apply#top",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_self_link(url, self.PAGE))

    def test_a_real_posting_url_is_kept(self) -> None:
        self.assertFalse(
            is_self_link("https://www.iitb.ac.in/careers/faculty-position-cse-2026", self.PAGE)
        )

    def test_it_never_raises_on_junk(self) -> None:
        # Runs inside extraction batches; raising would fail the batch over one
        # malformed href.
        for url in (None, "", "javascript:void(0)", "not a url", "mailto:x@y.z"):
            with self.subTest(url=url):
                self.assertIsInstance(is_self_link(url, self.PAGE), bool)


class TestTheStripperWasMeasuredAndRejected(unittest.TestCase):
    """`strip_page_chrome` exists, is documented, and is deliberately unused.

    Measured over ten sources, the vocabulary gate alone took databricks.com
    from 68 rows to 4 and rti.org from 76 to 3, and adding the chrome strip on
    top emptied rti.org and icmr.gov.in completely - it removes the regions
    real listings are nested in often enough that no scoping made it safe.
    """

    def test_extraction_does_not_call_it(self) -> None:
        source = (BACKEND_ROOT / "app" / "services" / "source_discovery.py").read_text()
        body = source.split("class TemplateDrivenScraper", 1)[-1]
        self.assertNotIn(
            "strip_page_chrome(",
            body,
            "the chrome stripper was measured to cost real rows; see its docstring",
        )

    def test_it_still_works_if_someone_revives_it(self) -> None:
        from bs4 import BeautifulSoup

        from app.services.source_discovery import strip_page_chrome

        soup = strip_page_chrome(
            BeautifulSoup("<body><nav><li>Donate</li></nav><main><li>Intern</li></main></body>", "html.parser")
        )
        self.assertEqual([li.get_text() for li in soup.select("li")], ["Intern"])


if __name__ == "__main__":
    unittest.main()
