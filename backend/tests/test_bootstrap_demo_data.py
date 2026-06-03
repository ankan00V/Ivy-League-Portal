import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.bootstrap_demo_data import build_seed_opportunity_payloads, canonical_url, stable_hash


class TestBootstrapDemoData(unittest.TestCase):
    def test_canonical_url_removes_tracking_params(self) -> None:
        url = canonical_url("https://www.demo.test/path/?utm_source=x&ref=abc&keep=yes")
        self.assertEqual(url, "https://demo.test/path?keep=yes")

    def test_seed_payloads_are_deterministic_and_unique(self) -> None:
        first = build_seed_opportunity_payloads(limit=4)
        second = build_seed_opportunity_payloads(limit=4)

        self.assertEqual([row["source_id"] for row in first], [row["source_id"] for row in second])
        self.assertEqual(len({row["url"] for row in first}), 4)
        self.assertEqual(len({row["canonical_url_hash"] for row in first}), 4)

    def test_seed_payloads_include_quality_trust_and_status_fields(self) -> None:
        row = build_seed_opportunity_payloads(limit=1)[0]

        self.assertEqual(row["source"], "bootstrap_demo_data")
        self.assertEqual(row["canonical_url_hash"], stable_hash(row["url"]))
        self.assertEqual(row["trust_status"], "verified")
        self.assertEqual(row["opportunity_status"], "active")
        self.assertEqual(row["lifecycle_status"], "published")
        self.assertGreaterEqual(row["quality_score"], 90.0)
        self.assertGreaterEqual(row["freshness_score"], 0.9)
        self.assertTrue(row["tags"])


if __name__ == "__main__":
    unittest.main()
