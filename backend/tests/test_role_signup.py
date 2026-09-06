"""Signing up as a role must produce an account of that role.

register_user computed the requested account type, used it to choose an email
rule, and then hardcoded "candidate" on the row it created. Registering as an
employer returned 200 and produced a candidate account. That is the worst shape
of wrong answer available: the caller is told it worked, and finds out later
from a portal that refuses them, with nothing anywhere connecting the two.

The other half is the email rule. It was an if/elif over candidate and employer,
so the two roles added afterwards had no rule at all - and one of them reads
cohort data about other people's students. A dispatch keyed on the role turns
"added a role and forgot its rule" into a visible omission rather than an open
door.
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
from app.core.account_types import CANDIDATE, EMPLOYER, FACULTY, INSTITUTION
from app.core.config import settings


class TestEveryRoleHasAnEmailRule(unittest.TestCase):
    def test_consumer_mailboxes_are_refused_for_every_role(self) -> None:
        # The regression: faculty and institution accepted anything at all.
        for role in (CANDIDATE, EMPLOYER, FACULTY, INSTITUTION):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException):
                    auth._ensure_email_policy_for_account_type(role, "someone@gmail.com")

    def test_institutional_addresses_are_accepted(self) -> None:
        for role in (CANDIDATE, FACULTY, INSTITUTION):
            with self.subTest(role=role):
                auth._ensure_email_policy_for_account_type(role, "someone@lpu.in")

    def test_employer_accepts_a_corporate_domain(self) -> None:
        auth._ensure_email_policy_for_account_type(EMPLOYER, "hr@acme.co")

    def test_an_unknown_role_is_not_silently_waved_through(self) -> None:
        # Nothing should reach account creation with an unrecognised role, but
        # if it does, the type gate is what refuses it - not this function
        # pretending the role was fine.
        with self.assertRaises(HTTPException):
            auth._normalize_account_type("recruiter")


class TestRequestedRoleIsHonoured(unittest.TestCase):
    def test_every_enabled_role_normalises_to_itself(self) -> None:
        # register_user builds the row from this value. While it hardcoded
        # "candidate", this function was correct and the account was still wrong,
        # so the property worth pinning is that the value survives.
        for role in (CANDIDATE, EMPLOYER, FACULTY, INSTITUTION):
            with self.subTest(role=role):
                self.assertEqual(auth._normalize_account_type(role), role)

    def test_a_disabled_role_is_refused_rather_than_downgraded(self) -> None:
        # Downgrading to candidate is exactly the behaviour this replaced: the
        # caller must be told no, not handed a different account.
        with patch.object(settings, "FACULTY_PORTAL_ENABLED", False):
            with self.assertRaises(HTTPException) as caught:
                auth._normalize_account_type(FACULTY)
            self.assertEqual(caught.exception.status_code, 400)

    def test_missing_role_still_defaults_to_candidate(self) -> None:
        self.assertEqual(auth._normalize_account_type(None), CANDIDATE)

    def test_stored_roles_keep_normalising_after_a_flag_is_turned_off(self) -> None:
        # An existing account must stay readable, exportable and deletable once
        # its role is withdrawn.
        with patch.object(settings, "INSTITUTION_PORTAL_ENABLED", False):
            self.assertEqual(
                auth._normalize_account_type(INSTITUTION, stored=True), INSTITUTION
            )


if __name__ == "__main__":
    unittest.main()
