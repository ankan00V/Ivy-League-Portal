import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import check_release_contracts


class TestReleaseContracts(unittest.TestCase):
    def test_release_contract_checker_passes_current_repo(self) -> None:
        self.assertEqual(check_release_contracts.main(), 0)

    def test_production_requires_both_neon_database_urls(self) -> None:
        parse_env = check_release_contracts._parse_env
        for missing_key in ("DATABASE_URL", "DATABASE_URL_UNPOOLED"):
            with self.subTest(missing_key=missing_key):
                def without_database_url(path):
                    values = parse_env(path)
                    if path.name == ".env.production.example":
                        values.pop(missing_key, None)
                    return values

                failures = []
                with patch.object(check_release_contracts, "_parse_env", side_effect=without_database_url):
                    check_release_contracts._check_env_contracts(failures)
                self.assertIn(f"backend/.env.production.example missing {missing_key}", failures)


if __name__ == "__main__":
    unittest.main()
