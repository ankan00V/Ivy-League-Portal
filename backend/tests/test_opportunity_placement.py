"""Feed placement pills: india, remote, hybrid, international.

The cases here are taken from real values in the live corpus, not invented. The
corpus is the whole difficulty: `work_mode` is null on 73% of rows, case-split where
present (`Remote` 256 / `remote` 23), and carries values that are not work modes at
all (`Intern`, `On-roll`, `Full-time Employment`). `location` is null on 38% and
sometimes holds a work mode (`In-Office`, `Hybrid`) or nothing usable
(`2 Locations`).

Two invariants matter more than any individual case:

1. **Pills overlap.** A remote internship in Bengaluru is both `india` and `remote`.
   Forcing one bucket per listing would hide remote Indian internships from the
   India pill, which is the first place a student looks.
2. **Unknown stays unknown.** A listing we cannot place gets no pill and shows only
   under "All". Guessing would put wrong listings in front of students, and there is
   a specific temptation to guess here — `opportunity_quality_service` already maps
   every remote listing to India, which this module deliberately does not copy.
"""
from __future__ import annotations

import pytest

from app.services.opportunity_placement import (
    FEED_CATEGORIES,
    classify_placement,
)


def cats(**kwargs) -> set[str]:
    return set(classify_placement(**kwargs))


class TestWorkModeFromExplicitField:
    @pytest.mark.parametrize("value", ["Remote", "remote", "  REMOTE  ", "Fully Remote", "WFH"])
    def test_remote_variants(self, value):
        assert "remote" in cats(work_mode=value)

    @pytest.mark.parametrize("value", ["Hybrid", "hybrid", "HYBRID"])
    def test_hybrid_variants(self, value):
        assert "hybrid" in cats(work_mode=value)

    def test_case_split_values_land_in_the_same_pill(self):
        """`Remote` (256 rows) and `remote` (23 rows) must not be two categories."""
        assert cats(work_mode="Remote") == cats(work_mode="remote")

    @pytest.mark.parametrize(
        "junk",
        ["Intern", "Full-time Employment", "On-roll", "Full Time Employee", "Full-time", "Contract"],
    )
    def test_employment_type_is_not_a_work_mode(self, junk):
        """These are real `work_mode` values in the corpus and describe hours, not place."""
        assert cats(work_mode=junk) == set()

    def test_onsite_produces_no_pill(self):
        """Onsite is real information but there is no onsite pill in this filter."""
        assert cats(work_mode="Onsite") == set()


class TestWorkModeFromLocationColumn:
    @pytest.mark.parametrize("value", ["Hybrid", "In-Office", "Remote"])
    def test_modes_stored_in_the_location_column_are_read(self, value):
        """Scrapers put these in `location`; 23 rows in the live corpus do exactly this."""
        result = cats(location=value)
        assert result <= {"remote", "hybrid"}

    def test_in_office_is_not_mistaken_for_a_place(self):
        assert cats(location="In-Office") == set()

    def test_unusable_location_yields_nothing(self):
        assert cats(location="2 Locations") == set()


class TestWorkModeFromText:
    def test_remote_recovered_from_description(self):
        """73% of rows have no work_mode; text is the only remaining signal."""
        assert "remote" in cats(
            work_mode=None, title="Data Science Intern", description="This is a fully remote role."
        )

    def test_hybrid_recovered_from_description(self):
        assert "hybrid" in cats(work_mode=None, description="Hybrid working, 3 days in office.")

    @pytest.mark.parametrize(
        "text",
        [
            "This role is not remote.",
            "No remote work available.",
            "Non remote position.",
            "This is not remote and requires relocation.",
        ],
    )
    def test_negated_mentions_do_not_count(self, text):
        """Without negation handling, 'not remote' reads as remote."""
        assert "remote" not in cats(work_mode=None, description=text)

    def test_explicit_field_wins_over_text(self):
        """A stored Onsite must not be overridden by the word 'remote' in prose."""
        result = cats(work_mode="Onsite", description="We are not a remote company.")
        assert "remote" not in result


class TestIndiaGeography:
    @pytest.mark.parametrize(
        "location",
        [
            "India",
            "Bangalore, India",
            "Bengaluru, Karnataka, India",
            "Mumbai, India",
            "Pune, India",
            "Gurugram, India",
            "Bengaluru-VTP, India",
            "Hyderabad, Telangana, India",
        ],
    )
    def test_explicit_india_values(self, location):
        assert "india" in cats(location=location)

    @pytest.mark.parametrize("location", ["Noida, Uttar Pradesh", "Bengaluru, Karnataka"])
    def test_indian_city_or_state_without_the_word_india(self, location):
        """Real corpus values. A naive 'contains india' check misses both."""
        assert "india" in cats(location=location)

    def test_punctuation_does_not_defeat_matching(self):
        assert "india" in cats(location="Bengaluru-VTP, India")

    def test_india_is_not_also_international(self):
        assert cats(location="Bangalore, India") == {"india"}


class TestInternationalGeography:
    @pytest.mark.parametrize(
        "location",
        [
            "San Jose, CA",
            "SF",
            "NYC",
            "Chicago, IL",
            "Boston, Massachusetts, USA",
            "Canada",
            "Dublin, Ireland",
            "United States",
            "Ho Chi Minh, vn",
            "Amsterdam",
            "Singapore, Singapore",
            "Gerlingen-Schillerhöhe, de",
        ],
    )
    def test_real_international_values(self, location):
        assert "international" in cats(location=location)

    def test_international_is_not_also_india(self):
        assert cats(location="San Jose, CA") == {"international"}


class TestOverlap:
    def test_remote_job_in_india_is_both(self):
        """The central design decision, as one assertion."""
        assert cats(location="Bangalore, India", work_mode="Remote") == {"india", "remote"}

    def test_hybrid_job_abroad_is_both(self):
        assert cats(location="Dublin, Ireland", work_mode="Hybrid") == {"hybrid", "international"}

    def test_returned_order_is_stable(self):
        """The UI renders pills in a fixed order; classification must not shuffle."""
        result = classify_placement(location="Bangalore, India", work_mode="Remote")
        assert result == [c for c in FEED_CATEGORIES if c in set(result)]


class TestUnknownStaysUnknown:
    def test_nothing_in_nothing_out(self):
        assert cats() == set()

    def test_remote_alone_is_not_assumed_indian(self):
        """`opportunity_quality_service.normalize_location` maps remote -> India.

        Copying that here would drop US remote roles into the India pill.
        """
        assert cats(work_mode="Remote") == {"remote"}

    def test_unplaceable_listing_gets_no_geography(self):
        result = cats(title="Graduate Hooding 2026", description="Ceremony coverage.")
        assert "india" not in result and "international" not in result


class TestSourceHint:
    @pytest.mark.parametrize("source", ["internshala", "unstop", "naukri", "freshersworld"])
    def test_india_only_boards_imply_india(self, source):
        """Internshala had 70 of 82 listings unplaceable on location alone."""
        assert "india" in cats(source=source)

    @pytest.mark.parametrize("source", ["linkedin", "glassdoor", "ycombinator_jobs", "wayup", "ivy_rss"])
    def test_global_boards_imply_nothing(self, source):
        assert cats(source=source) == set()

    def test_row_location_beats_the_source_hint(self):
        """An India-only board is a last resort, never an override."""
        assert cats(location="San Jose, CA", source="internshala") == {"international"}

    def test_source_hint_composes_with_work_mode(self):
        assert cats(work_mode="Remote", source="internshala") == {"india", "remote"}


class TestApiExposure:
    def test_response_model_exposes_feed_categories(self):
        from app.api.api_v1.endpoints.opportunities import OpportunityResponse

        assert "feed_categories" in OpportunityResponse.model_computed_fields

    def test_recommended_response_inherits_it(self):
        """The dashboard feed uses the subclass; it must carry the pills too."""
        from app.api.api_v1.endpoints.opportunities import RecommendedOpportunityResponse

        assert "feed_categories" in RecommendedOpportunityResponse.model_computed_fields
