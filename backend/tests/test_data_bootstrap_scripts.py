import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts import bootstrap_opportunities, seed_test_data, validate_data_health


class TestDataBootstrapScripts(unittest.TestCase):
    def test_bootstrap_opportunities_summarizes_scraper_sources(self) -> None:
        report = {
            "sources": [
                {"fetched": 10, "inserted": 7, "deduplicated": 3},
                {"items_fetched": 5, "items_inserted": 4, "items_deduplicated": 1},
            ]
        }
        self.assertEqual(
            bootstrap_opportunities._source_summary(report),
            {"total_fetched": 15, "total_inserted": 11, "total_deduplicated": 4},
        )

    def test_seed_personas_are_sufficient_for_twenty_users(self) -> None:
        self.assertGreaterEqual(len(seed_test_data.PERSONAS), 5)

    def test_validation_script_has_main_entrypoint(self) -> None:
        self.assertTrue(callable(validate_data_health.main))


if __name__ == "__main__":
    unittest.main()
