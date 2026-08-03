import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.skill_extractor import SkillExtractor, fallback_skill_tags, token_feature_rows, tokenize
from app.services.source_discovery import _extract_skill_tags


class TestSkillExtractor(unittest.TestCase):
    def test_keyword_fallback_is_case_insensitive_and_ordered(self) -> None:
        self.assertEqual(
            fallback_skill_tags("Build REACT services with Python, SQL, and machine learning."),
            ["python", "react", "sql", "machine learning"],
        )

    def test_missing_artifact_preserves_keyword_fallback(self) -> None:
        with patch("app.services.skill_extractor.settings.SKILL_EXTRACTOR_MODEL_PATH", "/tmp/missing-skill-extractor.joblib"):
            tags = SkillExtractor().extract("Python developer with React and SQL experience")

        self.assertEqual(tags, ["python", "react", "sql"])

    def test_token_features_keep_one_row_per_token(self) -> None:
        tokens = tokenize("C++ developer with Node.js")
        rows = token_feature_rows(tokens)

        self.assertEqual(len(rows), len(tokens))
        self.assertTrue(rows[0].startswith("token=c++"))
        self.assertIn("token=node.js", rows[-1])

    def test_source_discovery_delegates_tag_extraction(self) -> None:
        with patch("app.services.source_discovery.skill_extractor.extract", return_value=["docker", "postgresql"]) as extract:
            tags = _extract_skill_tags("ignored")

        self.assertEqual(tags, ["docker", "postgresql"])
        extract.assert_called_once_with("ignored", max_tags=8)


if __name__ == "__main__":
    unittest.main()
