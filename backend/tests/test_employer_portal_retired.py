"""The employer portal is retired but deliberately kept on disk.

These tests exist because "retired" is a state that rots quietly. The code is all
still there, so nothing fails loudly if the flag stops being honoured -- the
workflow would simply come back, and the way it comes back is as a self-serve
signup whose only gate is a non-freemail email domain. That is the exact hole
retirement was meant to close, so it gets a test rather than a comment.

Flipping EMPLOYER_PORTAL_ENABLED to True is the supported way to bring it back;
these tests assert the retired state, not that the feature is gone forever.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import auth
from app.core.config import settings


class TestEmployerPortalRetired(unittest.TestCase):
    def test_portal_is_disabled_by_default(self) -> None:
        self.assertFalse(
            settings.EMPLOYER_PORTAL_ENABLED,
            "Employer portal should stay retired until deliberately re-enabled.",
        )

    def test_employer_routes_are_not_mounted(self) -> None:
        from app.api.api_v1.api import api_router

        employer_routes = [
            route.path for route in api_router.routes if "/employer" in getattr(route, "path", "")
        ]
        self.assertEqual(
            employer_routes,
            [],
            "Retiring the portal means not mounting its routes; found: "
            f"{employer_routes}",
        )

    def test_employer_module_is_kept_on_disk(self) -> None:
        # Retired, not deleted. If this import breaks, the workflow can no longer
        # be restored by flipping the flag, which was the whole point.
        from app.api.api_v1.endpoints import employer

        self.assertTrue(hasattr(employer, "router"))

    def test_requested_employer_account_type_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            auth._normalize_account_type("employer")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("not available", str(caught.exception.detail))

    def test_stored_employer_account_type_still_normalizes(self) -> None:
        # An existing employer row must stay readable so it can be exported and
        # deleted. Refusing stored values would strand the account instead.
        self.assertEqual(
            auth._normalize_account_type("employer", stored=True),
            "employer",
        )

    def test_candidate_is_unaffected(self) -> None:
        self.assertEqual(auth._normalize_account_type("candidate"), "candidate")
        self.assertEqual(auth._normalize_account_type(None), "candidate")

    def test_flag_restores_employer_signup(self) -> None:
        # Guards against the rejection being hardcoded rather than flag-driven:
        # if this fails, the portal can no longer be switched back on.
        with patch.object(settings, "EMPLOYER_PORTAL_ENABLED", True):
            self.assertEqual(auth._normalize_account_type("employer"), "employer")

    def test_invalid_account_type_still_rejected(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            auth._normalize_account_type("recruiter")
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
