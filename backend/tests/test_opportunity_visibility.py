import unittest
from datetime import datetime, timedelta, timezone
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
        published = SimpleNamespace(lifecycle_status="published", deadline=now + timedelta(days=2), trust_status="verified", risk_score=12)
        expired = SimpleNamespace(lifecycle_status="published", deadline=now - timedelta(minutes=1))
        paused = SimpleNamespace(lifecycle_status="paused", deadline=now + timedelta(days=2), trust_status="verified", risk_score=12)
        blocked = SimpleNamespace(lifecycle_status="published", deadline=now + timedelta(days=2), trust_status="blocked", risk_score=92)

        self.assertTrue(is_student_visible_opportunity(published, now=now))
        self.assertTrue(is_opportunity_expired(expired, now=now))
        self.assertFalse(is_student_visible_opportunity(expired, now=now))
        self.assertFalse(is_student_visible_opportunity(paused, now=now))
        self.assertFalse(is_student_visible_opportunity(blocked, now=now))

    def test_is_student_visible_opportunity_accepts_naive_mongo_deadlines(self) -> None:
        now = datetime(2026, 5, 6, 4, 0, tzinfo=timezone.utc)
        naive_future = datetime(2026, 5, 7, 4, 0)
        naive_past = datetime(2026, 5, 5, 4, 0)

        published = SimpleNamespace(
            lifecycle_status="published",
            deadline=naive_future,
            trust_status="verified",
            risk_score=12,
        )
        expired = SimpleNamespace(
            lifecycle_status="published",
            deadline=naive_past,
            trust_status="verified",
            risk_score=12,
        )

        self.assertTrue(is_student_visible_opportunity(published, now=now))
        self.assertTrue(is_opportunity_expired(expired, now=now))


if __name__ == "__main__":
    unittest.main()
