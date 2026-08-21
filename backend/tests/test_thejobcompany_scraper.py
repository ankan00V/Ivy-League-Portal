"""Parser contract for thejobcompany.co.in.

Fixture is real markup captured from /job-category/batch/2026 on 2026-08-13, not
invented, so a site redesign fails these rather than silently returning zero rows.

Worth recording why this source took two attempts to evaluate: from the
university network its HTTPS appeared completely broken — TLS reset after 0 bytes
on 1.2 and 1.3. It was an SSL-intercepting proxy filtering the domain. SSL Labs
graded the same IP "A" from outside, and the site fetched fine on another
network. A local fetch failure here says more about the network than the site.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.scraper import THEJOBCOMPANY_LISTINGS, TheJobCompanyScraper

LISTING_URL = "https://thejobcompany.co.in/job-category/batch/2026"

FIXTURE = """
<div class="job-listings">
  <div class="job-listing">
    <img src="../../adminware/uploads/logos/1772214597.png" class="company-logo">
    <div class="company-split">
      <a href="../../frontend/job_details.php?job_id=6177" class="applyBtn">
        <p class="company-title">FanCode  is hiring Software Engineer Internship (Backend)</p>
        <p><strong>Batch :</strong> 2027 | 2026 </p>
        <p><strong>Location :</strong> Mumbai, India</p>
        <p><strong>Qualification :</strong> BE/B-TECH in CS or IT</p>
        <p><strong>Salary :</strong> 40,000-50,000/ Month (Stipend) [Expected]</p>
      </a>
    </div>
  </div>
  <div class="job-listing">
    <div class="company-split">
      <a href="../../frontend/job_details.php?job_id=6174" class="applyBtn">
        <p class="company-title">Curer is hiring for Software Engineer Intern</p>
        <p><strong>Batch :</strong> 2025 | 2026 | 2027 </p>
        <p><strong>Location :</strong> Work-from-home/Remote</p>
      </a>
    </div>
  </div>
  <div class="job-listing">
    <div class="company-split">
      <a href="../../frontend/job_details.php?job_id=6100" class="applyBtn">
        <p class="company-title">A posting with no recognisable split</p>
      </a>
    </div>
  </div>
</div>
"""


def parse():
    return TheJobCompanyScraper()._extract_cards(
        BeautifulSoup(FIXTURE, "html.parser"), LISTING_URL
    )


class TestCardExtraction:
    def test_every_card_is_parsed(self):
        assert len(parse()) == 3

    def test_company_is_split_out_of_the_title(self):
        """The employer appears nowhere else parseable — the logo is a numeric file."""
        row = parse()[0]
        assert row["university"] == "FanCode"
        assert row["title"] == "Software Engineer Internship (Backend)"

    def test_the_is_hiring_for_variant_also_splits(self):
        row = parse()[1]
        assert row["university"] == "Curer"
        assert row["title"] == "Software Engineer Intern"

    def test_an_unsplittable_title_keeps_the_whole_string(self):
        """Never invent an employer: better a blank company than a wrong one."""
        row = parse()[2]
        assert row["title"] == "A posting with no recognisable split"
        assert row["university"] == "The Job Company Employer"

    def test_relative_urls_are_absolutised(self):
        for row in parse():
            assert row["url"].startswith("https://thejobcompany.co.in/frontend/job_details.php?job_id=")


class TestLabelledFields:
    def test_batch_years_parse_to_integers(self):
        assert parse()[0]["batch_years"] == [2026, 2027]
        assert parse()[1]["batch_years"] == [2025, 2026, 2027]

    def test_label_is_stripped_from_the_value(self):
        """The <p> text includes the bold label; it must not leak into the value."""
        row = parse()[0]
        assert row["location"] == "Mumbai, India"
        assert "Location" not in str(row["location"])
        assert row["eligibility"] == "BE/B-TECH in CS or IT"
        assert row["stipend"].startswith("40,000-50,000")

    def test_missing_fields_are_none_not_empty_string(self):
        row = parse()[1]
        assert row["eligibility"] is None
        assert row["stipend"] is None

    def test_description_carries_the_labelled_context(self):
        text = parse()[0]["description"]
        assert "Mumbai, India" in text
        assert "BE/B-TECH" in text


class TestSourceIdentity:
    def test_source_key_is_stable(self):
        assert {row["source"] for row in parse()} == {"thejobcompany"}

    def test_registered_as_an_india_only_board(self):
        """Every listing is Indian, so the placement filter can lean on the source."""
        from app.services.opportunity_placement import _INDIA_ONLY_SOURCES, classify_placement

        assert "thejobcompany" in _INDIA_ONLY_SOURCES
        assert "india" in classify_placement(source="thejobcompany")

    def test_listings_target_near_term_batches(self):
        urls = [u for u, _ in THEJOBCOMPANY_LISTINGS]
        assert any("batch/2026" in u for u in urls)
        assert any("internships" in u for u in urls)
        # The site keeps categories back to 2018; those are useless to students.
        assert not any(f"batch/{year}" in u for u in urls for year in range(2018, 2025))


class TestFetchPath:
    def test_fetches_without_a_rendering_provider(self):
        """Server-rendered PHP — paying for a render provider would buy nothing."""
        import inspect

        source = inspect.getsource(TheJobCompanyScraper.fetch_live_opportunities)
        assert "render=False" in source

    def test_wired_into_the_scheduled_run(self):
        from app.services import scraper

        assert hasattr(scraper, "thejobcompany_scraper")
        run_source = inspect_source(scraper)
        assert 'source_key="thejobcompany"' in run_source
        assert "thejobcompany_result" in run_source


def inspect_source(module):
    import inspect

    return inspect.getsource(module)


class TestRejectionReasonNamesTheRealGate:
    """A rejection reason has to name the gate that actually failed.

    Extraction rejects on `confidence >= 0.7 and len(valid) >= 2`, but both
    branches reported "low_extraction_confidence". Nine discovered sources were
    filed that way with confidence 0.907 — comfortably over the bar — and
    qualification scores above 89, including builtin.com and
    careers.ingrammicro.com. Their real failure was parsing fewer than two
    listings, which is a selector or a thin page, not a bad parser. The label
    sent anyone auditing rejections after the wrong problem.
    """

    def test_high_confidence_is_not_reported_as_low_confidence(self):
        import inspect

        from app.services.source_discovery import AdaptiveExtractionService

        source = inspect.getsource(AdaptiveExtractionService)
        assert "too_few_opportunities" in source, (
            "a source that cleared the confidence bar but yielded too few rows must "
            "not be labelled low_extraction_confidence"
        )
        # Match the assignment, not the explanatory comment above it.
        low_at = source.index('rejection_reason = f"low_extraction_confidence')
        guard_at = source.index("if confidence < 0.7")
        assert guard_at < low_at, "the low-confidence label must sit behind a confidence check"

    def test_thin_pages_are_flagged_for_review(self):
        """Extraction worked, so a human should see why the page had no listings."""
        import inspect

        from app.services.source_discovery import AdaptiveExtractionService

        source = inspect.getsource(AdaptiveExtractionService)
        assert "elif confidence >= 0.7" in source
