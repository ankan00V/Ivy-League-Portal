import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.model_artifact_service import model_artifact_service
from app.services.personalization.learned_ranker import learned_ranker


class TestModelArtifactService(unittest.TestCase):
    def test_resolve_local_file_uri_and_existence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "ranker.txt"
            model_path.write_text("model", encoding="utf-8")
            with (
                patch("app.services.model_artifact_service.settings.LEARNED_RANKER_ARTIFACT_URI", model_path.as_uri()),
                patch("app.services.model_artifact_service.settings.LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256", ""),
            ):
                self.assertTrue(model_artifact_service.learned_ranker_artifact_exists())

    def test_missing_artifact_returns_false(self) -> None:
        with patch("app.services.model_artifact_service.settings.LEARNED_RANKER_ARTIFACT_URI", "file:///tmp/does-not-exist.lgb.txt"):
            self.assertFalse(model_artifact_service.learned_ranker_artifact_exists())

    def test_sync_artifact_verifies_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "ranker.txt"
            model_path.write_text("model", encoding="utf-8")
            checksum = sha256(b"model").hexdigest()
            result = model_artifact_service.sync_artifact(uri=model_path.as_uri(), expected_sha256=checksum)
            self.assertTrue(result.verified)
            self.assertEqual(result.checksum_sha256, checksum)

    def test_production_learned_ranker_requires_loadable_artifact(self) -> None:
        with (
            patch("app.services.personalization.learned_ranker.settings.ENVIRONMENT", "production"),
            patch("app.services.personalization.learned_ranker.settings.LEARNED_RANKER_ENABLED", True),
            patch("app.services.personalization.learned_ranker.settings.LEARNED_RANKER_REQUIRE_LOADED_IN_PRODUCTION", True),
            patch("app.services.personalization.learned_ranker.model_artifact_service.resolve_learned_ranker_uri", return_value=""),
        ):
            with self.assertRaises(RuntimeError):
                learned_ranker.ensure_loaded_for_production()


if __name__ == "__main__":
    unittest.main()
