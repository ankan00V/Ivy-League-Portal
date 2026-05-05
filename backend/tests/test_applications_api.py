import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from beanie import PydanticObjectId

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import applications as applications_endpoint


class _QueryField:
    def __eq__(self, other):  # noqa: ANN001,D401
        return other


class FakeApplication:
    user_id = _QueryField()
    opportunity_id = _QueryField()
    created_at = _QueryField()
    existing = None
    created_instances = []

    def __init__(self, **kwargs):
        self.id = PydanticObjectId("69e111317cdc2b7901074b83")
        self.user_id = kwargs["user_id"]
        self.opportunity_id = kwargs["opportunity_id"]
        self.status = kwargs["status"]
        self.automation_mode = kwargs["automation_mode"]
        self.automation_log = kwargs["automation_log"]
        self.submitted_at = kwargs["submitted_at"]
        self.created_at = datetime.now(timezone.utc)
        self.insert = AsyncMock()
        FakeApplication.created_instances.append(self)

    @classmethod
    async def find_one(cls, *args, **kwargs):  # noqa: ANN002,ANN003
        return cls.existing


class TestApplicationsApi(unittest.TestCase):
    def setUp(self) -> None:
        FakeApplication.existing = None
        FakeApplication.created_instances = []

    def test_apply_to_opportunity_saves_immediately(self) -> None:
        user_id = PydanticObjectId("69e111317cdc2b7901074b81")
        opportunity_id = PydanticObjectId("69e111317cdc2b7901074b82")
        current_user = SimpleNamespace(id=user_id)
        opportunity = SimpleNamespace(
            id=opportunity_id,
            title="Example Internship",
            description="Official internship listing from a known company with a real source page and role details.",
            url="https://linkedin.com/jobs/view/example-internship",
            domain="Engineering",
            opportunity_type="Internship",
            trust_status="verified",
            trust_score=88,
            risk_score=12,
            lifecycle_status="published",
        )

        with (
            patch.object(applications_endpoint, "Application", FakeApplication),
            patch.object(applications_endpoint.Opportunity, "get", new=AsyncMock(return_value=opportunity)),
            patch.object(applications_endpoint.interaction_service, "log_event", new=AsyncMock()) as mock_log_event,
        ):
            response = asyncio.run(
                applications_endpoint.apply_to_opportunity(
                    opportunity_id=opportunity_id,
                    current_user=current_user,
                )
            )

        self.assertEqual(len(FakeApplication.created_instances), 1)
        FakeApplication.created_instances[0].insert.assert_awaited_once()
        mock_log_event.assert_awaited_once()
        self.assertEqual(response.status, "In Progress")
        self.assertEqual(response.automation_mode, "manual_redirect")

    def test_apply_to_opportunity_returns_existing_row_without_failing(self) -> None:
        user_id = PydanticObjectId("69e111317cdc2b7901074b81")
        opportunity_id = PydanticObjectId("69e111317cdc2b7901074b82")
        current_user = SimpleNamespace(id=user_id)
        opportunity = SimpleNamespace(
            id=opportunity_id,
            title="Example Hackathon",
            description="Official hackathon listing from a verified organizer with clear eligibility and timeline.",
            url="https://devfolio.co/hackathons/example-hackathon",
            domain="Engineering",
            opportunity_type="Hackathon",
            trust_status="verified",
            trust_score=86,
            risk_score=14,
            lifecycle_status="published",
        )
        FakeApplication.existing = SimpleNamespace(
            id=PydanticObjectId("69e111317cdc2b7901074b83"),
            user_id=user_id,
            opportunity_id=opportunity_id,
            status="In Progress",
            automation_mode="manual_redirect",
            automation_log="{}",
            submitted_at=None,
            created_at=datetime.now(timezone.utc),
        )

        with (
            patch.object(applications_endpoint, "Application", FakeApplication),
            patch.object(applications_endpoint.Opportunity, "get", new=AsyncMock(return_value=opportunity)),
            patch.object(applications_endpoint.interaction_service, "log_event", new=AsyncMock()) as mock_log_event,
        ):
            response = asyncio.run(
                applications_endpoint.apply_to_opportunity(
                    opportunity_id=opportunity_id,
                    current_user=current_user,
                )
            )

        self.assertEqual(len(FakeApplication.created_instances), 0)
        mock_log_event.assert_not_awaited()
        self.assertEqual(response.id, FakeApplication.existing.id)
        self.assertEqual(response.status, "In Progress")

    def test_apply_to_opportunity_succeeds_when_analytics_logging_fails(self) -> None:
        user_id = PydanticObjectId("69e111317cdc2b7901074b81")
        opportunity_id = PydanticObjectId("69e111317cdc2b7901074b82")
        current_user = SimpleNamespace(id=user_id)
        opportunity = SimpleNamespace(
            id=opportunity_id,
            title="Example Fellowship",
            description="Official fellowship listing with published requirements, institution context, and clear application flow.",
            url="https://wellfound.com/jobs/example-fellowship",
            domain="Research",
            opportunity_type="Opportunity",
            trust_status="verified",
            trust_score=80,
            risk_score=20,
            lifecycle_status="published",
        )

        with (
            patch.object(applications_endpoint, "Application", FakeApplication),
            patch.object(applications_endpoint.Opportunity, "get", new=AsyncMock(return_value=opportunity)),
            patch.object(
                applications_endpoint.interaction_service,
                "log_event",
                new=AsyncMock(side_effect=RuntimeError("analytics offline")),
            ),
        ):
            response = asyncio.run(
                applications_endpoint.apply_to_opportunity(
                    opportunity_id=opportunity_id,
                    current_user=current_user,
                )
            )

        self.assertEqual(len(FakeApplication.created_instances), 1)
        FakeApplication.created_instances[0].insert.assert_awaited_once()
        self.assertEqual(response.status, "In Progress")

    def test_apply_to_opportunity_rejects_blocked_opportunity(self) -> None:
        user_id = PydanticObjectId("69e111317cdc2b7901074b81")
        opportunity_id = PydanticObjectId("69e111317cdc2b7901074b82")
        current_user = SimpleNamespace(id=user_id)
        opportunity = SimpleNamespace(
            id=opportunity_id,
            title="Pay to apply internship",
            description="Pay Rs 999 application fee to reserve your internship spot.",
            url="https://random-opportunity-example.com/apply",
            domain="Engineering",
            opportunity_type="Internship",
            trust_status="blocked",
            risk_score=95,
            lifecycle_status="published",
        )

        with (
            patch.object(applications_endpoint, "Application", FakeApplication),
            patch.object(applications_endpoint.Opportunity, "get", new=AsyncMock(return_value=opportunity)),
        ):
            with self.assertRaises(applications_endpoint.HTTPException) as context:
                asyncio.run(
                    applications_endpoint.apply_to_opportunity(
                        opportunity_id=opportunity_id,
                        current_user=current_user,
                    )
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("not eligible", str(context.exception.detail))
