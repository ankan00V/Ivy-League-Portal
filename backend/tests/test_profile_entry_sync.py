"""Structured education/experience entries must keep the flat fields honest.

Education and work history became lists, because a student has a school and a
college and usually several short internships - the single college_name /
current_job_role fields could only ever hold the most recent.

Those flat fields could not simply be dropped: personalization and the ranker
read them (services/personalization/feature_builder.py). If the lists became the
thing users edit while the flat columns kept whatever the old single-value form
last wrote, recommendations would quietly drift away from the profile the user
can see - and nothing would fail, which is how that goes unnoticed for months.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints.users import _sync_flat_fields_from_entries
from app.models.profile import EducationEntry, ExperienceEntry, Profile
from beanie import PydanticObjectId


def setUpModule() -> None:
    """Constructing a Document needs the ODM bound; patching is enough, no DB."""
    from app.db import pg_documents

    pg_documents.install([Profile])


def _profile(**kwargs) -> Profile:
    return Profile(user_id=PydanticObjectId(), **kwargs)


class TestEducationSync(unittest.TestCase):
    def test_newest_education_drives_the_flat_fields(self) -> None:
        profile = _profile(
            education_entries=[
                EducationEntry(school="Dayanand School", degree="High School", end_year=2023),
                EducationEntry(
                    school="Lovely Professional University",
                    degree="B.Tech",
                    field_of_study="Computer Science",
                    end_year=2027,
                ),
            ]
        )
        _sync_flat_fields_from_entries(profile)
        self.assertEqual(profile.college_name, "Lovely Professional University")
        self.assertEqual(profile.course, "B.Tech")
        self.assertEqual(profile.course_specialization, "Computer Science")
        self.assertEqual(profile.passout_year, 2027)

    def test_school_entry_does_not_overwrite_the_degree(self) -> None:
        # Order in the list must not decide; the later end_year must.
        profile = _profile(
            education_entries=[
                EducationEntry(school="LPU", degree="B.Tech", end_year=2027),
                EducationEntry(school="Dayanand School", degree="High School", end_year=2023),
            ]
        )
        _sync_flat_fields_from_entries(profile)
        self.assertEqual(profile.college_name, "LPU")
        self.assertEqual(profile.passout_year, 2027)


class TestExperienceSync(unittest.TestCase):
    def test_current_role_wins_over_a_more_recent_end_date(self) -> None:
        profile = _profile(
            experience_entries=[
                ExperienceEntry(title="Software Developer", organization="NIIT", end_year=2026, end_month=8),
                ExperienceEntry(title="Open Source Contributor", organization="GSSoC",
                                is_current=True, start_year=2026, start_month=5),
            ]
        )
        _sync_flat_fields_from_entries(profile)
        self.assertEqual(profile.current_job_role, "Open Source Contributor")

    def test_falls_back_to_the_newest_when_nothing_is_current(self) -> None:
        profile = _profile(
            experience_entries=[
                ExperienceEntry(title="Intern", organization="A", end_year=2024),
                ExperienceEntry(title="Analyst", organization="B", end_year=2026),
            ]
        )
        _sync_flat_fields_from_entries(profile)
        self.assertEqual(profile.current_job_role, "Analyst")


class TestSkillsPropagation(unittest.TestCase):
    def test_entry_skills_join_the_profile_skills(self) -> None:
        profile = _profile(
            skills="Django",
            education_entries=[EducationEntry(school="LPU", skills=["Python", "SQL"])],
            experience_entries=[ExperienceEntry(title="Intern", organization="NIIT", skills=["FastAPI"])],
        )
        _sync_flat_fields_from_entries(profile)
        skills = [s.strip() for s in profile.skills.split(",")]
        self.assertEqual(skills, ["Django", "Python", "SQL", "FastAPI"])

    def test_existing_skills_are_not_duplicated(self) -> None:
        profile = _profile(
            skills="Python, SQL",
            education_entries=[EducationEntry(school="LPU", skills=["python", "Rust"])],
        )
        _sync_flat_fields_from_entries(profile)
        skills = [s.strip() for s in profile.skills.split(",")]
        self.assertEqual(skills, ["Python", "SQL", "Rust"])

    def test_no_entries_leaves_the_profile_untouched(self) -> None:
        profile = _profile(skills="Python", college_name="Existing College", current_job_role="Existing Role")
        _sync_flat_fields_from_entries(profile)
        self.assertEqual(profile.skills, "Python")
        self.assertEqual(profile.college_name, "Existing College")
        self.assertEqual(profile.current_job_role, "Existing Role")


if __name__ == "__main__":
    unittest.main()
