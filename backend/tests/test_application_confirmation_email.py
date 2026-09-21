"""The thank-you email a student gets after clicking Apply.

Tested through the apply endpoint, not only the email function: the useful
guarantees are about when it is sent (once, for a new application, without
delaying the redirect) as much as what it says.
"""

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
from app.services import email as email_service
from tests.test_applications_api import FakeApplication

USER_ID = PydanticObjectId("69e111317cdc2b7901074b81")
OPPORTUNITY_ID = PydanticObjectId("69e111317cdc2b7901074b82")


def _opportunity(**overrides):
    values = dict(
        id=OPPORTUNITY_ID,
        title="Analytics Engineer Intern",
        description="Official internship listing from a known company with a real source page and role details.",
        url="https://jobs.lever.co/example/analytics-intern",
        domain="Engineering",
        opportunity_type="Internship",
        university="Coinbase",
        trust_status="verified",
        trust_score=88,
        risk_score=12,
        lifecycle_status="published",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _user():
    return SimpleNamespace(id=USER_ID, email="student@lpu.in", full_name="ankan ghosh")


class TestApplyQueuesConfirmation(unittest.TestCase):
    def setUp(self) -> None:
        FakeApplication.existing = None
        FakeApplication.created_instances = []

    def _apply(self, send: AsyncMock) -> None:
        async def run() -> None:
            await applications_endpoint.apply_to_opportunity(
                opportunity_id=OPPORTUNITY_ID, current_user=_user()
            )
            # Let the background task run before the loop closes.
            await asyncio.gather(*list(applications_endpoint._confirmation_tasks))

        with (
            patch.object(applications_endpoint, "Application", FakeApplication),
            patch.object(applications_endpoint.Opportunity, "get", new=AsyncMock(return_value=_opportunity())),
            patch.object(applications_endpoint.interaction_service, "log_event", new=AsyncMock()),
            patch.object(applications_endpoint, "send_application_confirmation", send),
        ):
            asyncio.run(run())

    def test_new_application_sends_one_email_with_its_details(self) -> None:
        send = AsyncMock(return_value=True)
        self._apply(send)

        send.assert_awaited_once()
        kwargs = send.await_args.kwargs
        self.assertEqual(kwargs["to_email"], "student@lpu.in")
        self.assertEqual(kwargs["position"], "Analytics Engineer Intern")
        self.assertEqual(kwargs["company"], "Coinbase")
        self.assertEqual(kwargs["application_id"], str(FakeApplication.created_instances[0].id))
        self.assertEqual(kwargs["opportunity_url"], "https://jobs.lever.co/example/analytics-intern")

    def test_second_click_on_apply_sends_nothing(self) -> None:
        FakeApplication.existing = SimpleNamespace(
            id=PydanticObjectId("69e111317cdc2b7901074b83"),
            user_id=USER_ID,
            opportunity_id=OPPORTUNITY_ID,
            status="In Progress",
            automation_mode="manual_redirect",
            automation_log="{}",
            submitted_at=None,
            created_at=datetime.now(timezone.utc),
        )
        send = AsyncMock(return_value=True)
        self._apply(send)
        send.assert_not_awaited()


class TestConfirmationEmail(unittest.IsolatedAsyncioTestCase):
    async def _render(self, **overrides):
        deliver = AsyncMock()
        kwargs = dict(
            to_email="student@lpu.in",
            full_name="ankan ghosh",
            position="Analytics Engineer Intern",
            company="Coinbase",
            application_id="69e111317cdc2b7901074b83",
            opportunity_url="https://jobs.lever.co/example/analytics-intern",
        )
        kwargs.update(overrides)
        with patch.object(email_service, "_deliver_message", deliver):
            sent = await email_service.send_application_confirmation(**kwargs)
        return sent, deliver.await_args.kwargs if deliver.await_args else None

    async def test_names_the_student_the_role_the_company_and_the_reference(self) -> None:
        sent, message = await self._render()
        self.assertTrue(sent)
        text = message["text_body"]
        self.assertTrue(text.startswith("Hi Ankan,"))
        self.assertIn("the Analytics Engineer Intern role at Coinbase", text)
        self.assertIn("69e111317cdc2b7901074b83", text)
        self.assertIn("A little about us:", text)
        self.assertIn("Talent Team @ VidyaVerse", text)
        self.assertIn("Coinbase", message["subject"])

    async def test_placeholder_company_is_left_out_rather_than_thanked(self) -> None:
        _, message = await self._render(company="Glassdoor Employers")
        self.assertNotIn("Glassdoor", message["text_body"])
        self.assertIn("the Analytics Engineer Intern role.", message["text_body"])

    async def test_missing_name_still_reads_as_a_greeting(self) -> None:
        _, message = await self._render(full_name=None)
        self.assertTrue(message["text_body"].startswith("Hi there,"))

    async def test_scraped_text_is_escaped_in_html(self) -> None:
        _, message = await self._render(position="<script>x</script> Intern", company="A&B Labs")
        self.assertNotIn("<script>", message["html_body"])
        self.assertIn("A&amp;B Labs", message["html_body"])

    async def test_delivery_failure_is_reported_not_raised(self) -> None:
        with patch.object(email_service, "_deliver_message", AsyncMock(side_effect=RuntimeError("down"))):
            sent = await email_service.send_application_confirmation(
                to_email="student@lpu.in",
                full_name="Ankan",
                position="Intern",
                company="Bosch",
                application_id="x",
                opportunity_url="https://example.com",
            )
        self.assertFalse(sent)


if __name__ == "__main__":
    unittest.main()
