"""The employer portal is live, and publishing is gated on domain control.

This portal was retired once, and the reason matters: the only gate on employer
powers was a non-freemail email address, so self-serve signup let anyone with a
bought domain post straight into the feed candidates trust. Retirement closed
that by switching the whole workflow off.

It is back on, because industries posting their own openings is the point of the
academia-industry workflow. The hole is closed differently now - an employer may
draft and edit freely, but moving a listing to "published" requires a verified
careers-page claim, which is a token placed on the company's own domain. A
corporate-looking mailbox proves nothing; controlling the domain proves
something.

So the property worth pinning is not "employers exist" but "an unverified
employer cannot reach candidates". That has no visible symptom when it breaks:
the listing publishes, looks entirely normal in the feed, and nobody finds out
until the company it names complains.
"""

import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth
from app.api.api_v1.endpoints import employer
from app.core.config import settings


class TestPortalIsLive(unittest.TestCase):
    def test_portal_is_enabled(self) -> None:
        self.assertTrue(settings.EMPLOYER_PORTAL_ENABLED)

    def test_the_employer_endpoints_exist(self) -> None:
        """The fourteen routes are defined, unconditionally, on the module."""
        from app.api.api_v1.endpoints import employer

        paths = [getattr(route, "path", "") for route in employer.router.routes]
        self.assertIn("/opportunities", paths)
        self.assertGreaterEqual(len(paths), 10)

    def test_mounting_the_router_yields_employer_paths(self) -> None:
        """Mounting is exercised, not inspected after the fact.

        Two earlier versions of this test read the cached `api_router` and
        asserted it carried /employer paths. Both passed locally and failed on
        CI with a bare `[] is not true`, because the module decides what to
        mount at import time and the assertion therefore depended on when some
        other test first imported it - and `importlib.reload` did not make that
        deterministic either.

        Building a router here and mounting the real one into it asks the same
        question with no import-order or reload semantics in the way: given the
        employer router, does mounting it under the prefix produce the paths
        the portal is supposed to serve?
        """
        from fastapi import APIRouter

        from app.api.api_v1.endpoints import employer

        probe = APIRouter()
        probe.include_router(employer.router, prefix="/employer", tags=["employer"])
        paths = [getattr(route, "path", "") for route in probe.routes]
        self.assertIn("/employer/opportunities", paths)

    def test_the_flag_is_what_gates_the_mount(self) -> None:
        """The flag has to close the endpoints, not merely refuse the account.

        Refusing the account type stops new employers; it does nothing about
        anyone already holding a token, who would keep reaching all fourteen
        routes. Asserted against the source because the alternative - reloading
        the module under a patched flag - is the fragility described above.
        """
        api_source = (
            BACKEND_ROOT / "app" / "api" / "api_v1" / "api.py"
        ).read_text(encoding="utf-8")
        marker = 'api_router.include_router(employer.router'
        self.assertIn(marker, api_source)
        preceding = api_source.split(marker)[0]
        self.assertIn(
            "if settings.EMPLOYER_PORTAL_ENABLED:",
            preceding[-200:],
            "the employer mount must sit directly under the portal flag",
        )

    def test_employer_account_type_is_accepted(self) -> None:
        self.assertEqual(auth._normalize_account_type("employer"), "employer")

    def test_candidate_is_unaffected(self) -> None:
        self.assertEqual(auth._normalize_account_type("candidate"), "candidate")
        self.assertEqual(auth._normalize_account_type(None), "candidate")

    def test_invalid_account_type_still_rejected(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            auth._normalize_account_type("recruiter")
        self.assertEqual(caught.exception.status_code, 400)

    def test_flag_still_drives_the_refusal(self) -> None:
        # The gate must stay flag-driven in both directions, so the workflow can
        # be switched off again without editing call sites.
        with patch.object(settings, "EMPLOYER_PORTAL_ENABLED", False):
            with self.assertRaises(HTTPException) as caught:
                auth._normalize_account_type("employer")
            self.assertEqual(caught.exception.status_code, 400)


class TestPublishRequiresVerifiedDomain(unittest.IsolatedAsyncioTestCase):
    def _user(self, *, is_admin: bool = False):
        return SimpleNamespace(id="u1", is_admin=is_admin, account_type="employer")

    async def _gate(self, user, claim):
        with patch.object(
            employer.employer_claim_service, "latest_for_user", AsyncMock(return_value=claim)
        ):
            await employer._require_verified_employer(user)

    async def test_verified_claim_may_publish(self) -> None:
        claim = SimpleNamespace(verification_status="verified")
        await self._gate(self._user(), claim)  # must not raise

    async def test_unclaimed_employer_cannot_publish(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._gate(self._user(), None)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("verified careers page", str(caught.exception.detail))

    async def test_pending_claim_cannot_publish(self) -> None:
        # The dangerous near-miss: a claim exists, so the employer looks
        # legitimate in the UI, but the token was never found on the domain.
        claim = SimpleNamespace(verification_status="pending")
        with self.assertRaises(HTTPException) as caught:
            await self._gate(self._user(), claim)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_status_match_is_case_insensitive(self) -> None:
        await self._gate(self._user(), SimpleNamespace(verification_status="VERIFIED"))

    async def test_admin_bypasses_verification(self) -> None:
        # Admins are the ones who verify; requiring them to claim a careers page
        # would make the first verification impossible.
        with patch.object(
            employer.employer_claim_service, "latest_for_user", AsyncMock(return_value=None)
        ) as loader:
            await employer._require_verified_employer(self._user(is_admin=True))
        loader.assert_not_awaited()


class _StubField:
    """Stands in for a Beanie field so `Model.field == value` is expressible.

    The ODM patches these onto the document classes at startup, which unit tests
    do not run, so touching Profile.user_id raises AttributeError long before the
    code under test is reached.
    """

    def __eq__(self, other):  # noqa: D105
        return ("eq", other)

    def __hash__(self):  # noqa: D105
        return id(self)


class _StubDoc:
    user_id = _StubField()
    url = _StubField()

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    @staticmethod
    async def find_one(*_args, **_kwargs):
        return None

    async def insert(self):
        raise RuntimeError("no database in unit tests")


class TestTheEndpointActuallyCallsTheGate(unittest.IsolatedAsyncioTestCase):
    """A helper that refuses correctly is worthless if no route calls it.

    These drive the endpoint functions themselves, because the failure this
    guards against is not "the check is wrong" but "the check was never wired
    in" - which looks identical in a unit test of the helper alone.
    """

    def _payload(self, status: str):
        return employer.EmployerOpportunityCreate(
            title="Ayurveda Research Intern",
            description="A twelve week research internship working on formulations.",
            application_url="https://example.com/careers/intern-001",
            opportunity_type="Internship",
            lifecycle_status=status,
        )

    async def test_create_published_is_refused_without_verification(self) -> None:
        user = SimpleNamespace(
            id="u1", is_admin=False, account_type="employer", full_name="Acme Labs"
        )
        with (
            patch.object(employer, "Profile", _StubDoc),
            patch.object(employer, "Opportunity", _StubDoc),
            patch.object(
                employer.employer_claim_service, "latest_for_user", AsyncMock(return_value=None)
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                await employer.create_employer_opportunity(
                    payload=self._payload("published"), current_user=user
                )
        self.assertEqual(caught.exception.status_code, 403)

    async def test_create_draft_does_not_require_verification(self) -> None:
        # Verification gates reach, not access. A draft must never consult it.
        user = SimpleNamespace(
            id="u1", is_admin=False, account_type="employer", full_name="Acme Labs"
        )
        loader = AsyncMock(return_value=None)
        with (
            patch.object(employer, "Profile", _StubDoc),
            patch.object(employer, "Opportunity", _StubDoc),
            patch.object(employer.employer_claim_service, "latest_for_user", loader),
        ):
            try:
                await employer.create_employer_opportunity(
                    payload=self._payload("draft"), current_user=user
                )
            except HTTPException:
                raise
            except Exception:
                # Persisting needs a database; reaching it is the assertion.
                pass
        loader.assert_not_awaited()

    async def test_lifecycle_publish_is_refused_without_verification(self) -> None:
        user = SimpleNamespace(
            id="u1", is_admin=False, account_type="employer", full_name="Acme Labs"
        )
        opp = SimpleNamespace(
            id="o1", posted_by_user_id="u1", lifecycle_status="draft"
        )
        with (
            patch.object(employer, "PydanticObjectId", lambda v: v),
            patch.object(employer.Opportunity, "get", AsyncMock(return_value=opp)),
            patch.object(
                employer.employer_claim_service, "latest_for_user", AsyncMock(return_value=None)
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                await employer.update_opportunity_lifecycle(
                    opportunity_id="o1",
                    payload=employer.LifecycleUpdateRequest(status="published"),
                    current_user=user,
                )
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
