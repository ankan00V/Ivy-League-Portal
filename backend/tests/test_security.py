import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.security import verify_password


class TestSecurityPasswordVerification(unittest.TestCase):
    def test_verify_password_returns_backend_result_when_hash_is_valid(self) -> None:
        with patch("app.core.security.pwd_context.verify", return_value=True):
            self.assertTrue(verify_password("correct-horse-battery-staple", "$2b$dummy"))

    def test_verify_password_returns_false_for_unknown_hash_format(self) -> None:
        self.assertFalse(verify_password("any-password", "OTP_NO_PASSWORD"))


if __name__ == "__main__":
    unittest.main()
