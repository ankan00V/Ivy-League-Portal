import unittest
from fastapi import HTTPException

from app.api.api_v1.endpoints import admin as admin_endpoint


class TestAdminOpportunities(unittest.TestCase):
    def test_normalize_ppo_available_accepts_expected_values(self) -> None:
        self.assertEqual(admin_endpoint._normalize_ppo_available(" yes "), "yes")
        self.assertEqual(admin_endpoint._normalize_ppo_available("No"), "no")
        self.assertEqual(admin_endpoint._normalize_ppo_available("undefined"), "undefined")
        self.assertIsNone(admin_endpoint._normalize_ppo_available(""))

    def test_normalize_ppo_available_rejects_unexpected_values(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
          admin_endpoint._normalize_ppo_available("maybe")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
