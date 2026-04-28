import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.time import utc_now
from app.services.opportunity_visibility import (
    canonical_opportunity_type,
    is_opportunity_expired,
    is_student_visible_opportunity,
    resolve_opportunity_portal,
)


class TestOpportunityVisibility(unittest.TestCase):
    def test_canonical_opportunity_type_normalizes_admin_values(self) -> None:
        self.assertEqual(canonical_opportunity_type("job"), "Job")
        self.assertEqual(canonical_opportunity_type(" hiring challenge "), "Hiring Challenge")
        self.assertEqual(canonical_opportunity_type("hackathon"), "Hackathon")

    def test_resolve_opportunity_portal_prefers_explicit_portal_category(self) -> None:
        portal = resolve_opportunity_portal(
            opportunity_type="Job",
            title="Backend Engineer",
            description="Career role",
            portal_category="competitive",
        )
        self.assertEqual(portal, "competitive")

    def test_resolve_opportunity_portal_uses_explicit_types(self) -> None:
        self.assertEqual(resolve_opportunity_portal(opportunity_type="Internship"), "career")
        self.assertEqual(resolve_opportunity_portal(opportunity_type="Hackathon"), "competitive")

    def test_is_student_visible_opportunity_rejects_expired_or_unpublished_rows(self) -> None:
        now = utc_now()
        published = SimpleNamespace(lifecycle_status="published", deadline=now + timedelta(days=2))
        expired = SimpleNamespace(lifecycle_status="published", deadline=now - timedelta(minutes=1))
        paused = SimpleNamespace(lifecycle_status="paused", deadline=now + timedelta(days=2))

        self.assertTrue(is_student_visible_opportunity(published, now=now))
        self.assertTrue(is_opportunity_expired(expired, now=now))
        self.assertFalse(is_student_visible_opportunity(expired, now=now))
        self.assertFalse(is_student_visible_opportunity(paused, now=now))


if __name__ == "__main__":
    unittest.main()
