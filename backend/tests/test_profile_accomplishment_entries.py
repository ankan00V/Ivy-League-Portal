"""Structured accomplishments: projects, certifications, honors, volunteering.

These replaced four free-text columns (achievements / certificates / projects /
responsibilities). The old columns are deliberately still there and still
readable - a paragraph cannot be split into entries reliably, so nothing tries
to migrate them behind the user's back.

The properties worth pinning are the ones with no visible symptom when they
break: an "I'm still doing this" flag that leaves a stale end date behind it
renders as something which both ended and is ongoing, and duplicate skills
accumulate silently every time a user re-saves their profile.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.profile import (
    CertificationEntry,
    HonorEntry,
    Profile,
    ProjectEntry,
    VolunteerEntry,
)


class TestOngoingEntriesClearEndDates(unittest.TestCase):
    def test_current_project_drops_any_end_date(self) -> None:
        entry = ProjectEntry(
            name="VidyaVerse", is_current=True, start_year=2026, end_month=5, end_year=2030
        )
        self.assertIsNone(entry.end_month)
        self.assertIsNone(entry.end_year)

    def test_current_volunteering_drops_any_end_date(self) -> None:
        entry = VolunteerEntry(
            organization="Red Cross", role="Educator", is_current=True, end_year=2029
        )
        self.assertIsNone(entry.end_year)

    def test_finished_entry_keeps_its_end_date(self) -> None:
        entry = ProjectEntry(name="LPU Smart Campus", is_current=False, end_month=5, end_year=2026)
        self.assertEqual((entry.end_month, entry.end_year), (5, 2026))


class TestEntryNormalisation(unittest.TestCase):
    def test_skills_are_trimmed_and_deduped_case_insensitively(self) -> None:
        entry = ProjectEntry(name="x", skills=[" FastAPI ", "fastapi", "FASTAPI", "", "Next.js"])
        self.assertEqual(entry.skills, ["FastAPI", "Next.js"])

    def test_blank_text_becomes_none_rather_than_empty_string(self) -> None:
        # Empty strings render as blank lines on a profile; None is skipped.
        entry = CertificationEntry(name="Redis Associate", issuing_organization="   ")
        self.assertIsNone(entry.issuing_organization)

    def test_honor_fields_are_trimmed(self) -> None:
        entry = HonorEntry(title="  Rank 2  ", issuer="  AlgoUniversity ")
        self.assertEqual(entry.title, "Rank 2")
        self.assertEqual(entry.issuer, "AlgoUniversity")

    def test_month_bounds_are_enforced(self) -> None:
        for bad_month in (0, 13):
            with self.subTest(month=bad_month):
                with self.assertRaises(Exception):
                    CertificationEntry(name="x", issue_month=bad_month)


class TestProfileHoldsTheLists(unittest.TestCase):
    def test_entry_lists_default_to_empty_not_none(self) -> None:
        # The ODM writes these to jsonb columns defaulting to '[]', and the UI
        # maps over them directly; None would be a crash rather than an absence.
        fields = Profile.model_fields
        for name in (
            "project_entries",
            "certification_entries",
            "honor_entries",
            "volunteer_entries",
        ):
            with self.subTest(field=name):
                self.assertIn(name, fields)
                self.assertEqual(fields[name].default_factory(), [])

    def test_free_text_columns_are_retained(self) -> None:
        # Nothing migrates the old prose automatically, so dropping these would
        # destroy what users typed before the structured lists existed.
        for legacy in ("achievements", "certificates", "projects", "responsibilities"):
            with self.subTest(field=legacy):
                self.assertIn(legacy, Profile.model_fields)


if __name__ == "__main__":
    unittest.main()
