import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.security import verify_password
from app.api.api_v1.endpoints import auth as auth_endpoint


class TestSecurityPasswordVerification(unittest.TestCase):
    def test_verify_password_returns_backend_result_when_hash_is_valid(self) -> None:
        with patch("app.core.security.pwd_context.verify", return_value=True):
            self.assertTrue(verify_password("correct-horse-battery-staple", "$2b$dummy"))

    def test_verify_password_returns_false_for_unknown_hash_format(self) -> None:
        self.assertFalse(verify_password("any-password", "OTP_NO_PASSWORD"))

    def test_password_setup_detection_covers_legacy_sentinel_hashes(self) -> None:
        self.assertTrue(auth_endpoint._user_needs_password_setup(SimpleNamespace(hashed_password="OTP_NO_PASSWORD")))
        self.assertTrue(auth_endpoint._user_needs_password_setup(SimpleNamespace(hashed_password="OAUTH_GOOGLE_NO_PASSWORD")))
        self.assertFalse(auth_endpoint._user_needs_password_setup(SimpleNamespace(hashed_password="$2b$hash")))

    def test_password_policy_requires_core_strength_parameters(self) -> None:
        self.assertIn("Use at least 8 characters", auth_endpoint._password_policy_issues("Aa1"))
        self.assertEqual(auth_endpoint._password_policy_issues("StrongPass1"), [])


if __name__ == "__main__":
    unittest.main()
