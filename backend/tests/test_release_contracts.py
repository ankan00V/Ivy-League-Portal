import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import check_release_contracts


class TestReleaseContracts(unittest.TestCase):
    def test_release_contract_checker_passes_current_repo(self) -> None:
        self.assertEqual(check_release_contracts.main(), 0)


if __name__ == "__main__":
    unittest.main()
