"""A withdrawn model must not be able to silently disable Ask AI.

Every LLM path here catches provider errors and serves a deterministic answer,
which is right for a timeout and exactly wrong for an HTTP 410: the product keeps
returning well-formed answers and nothing on screen says the model was never
consulted. That is how Ask AI ran from 2026-08-26 without anyone noticing.
"""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.llm_models import live_model


class TestRetiredModelGuard(unittest.TestCase):
    def test_a_retired_model_is_replaced(self) -> None:
        self.assertEqual(
            live_model("meta/llama-3.1-8b-instruct", fallback="live/model", context="test"),
            "live/model",
        )

    def test_a_live_model_is_left_alone(self) -> None:
        self.assertEqual(
            live_model("some/live-model", fallback="live/model", context="test"),
            "some/live-model",
        )

    def test_an_empty_setting_falls_back(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(live_model(value, fallback="live/model", context="t"), "live/model")

    def test_ask_ai_resolves_to_a_live_model(self) -> None:
        # The end-to-end property: whatever the deployment's .env names, Ask AI
        # is never constructed pointing at a model the provider has withdrawn.
        from app.core.config import settings
        from app.services.rag_service import RAGService

        retired = set(settings.RETIRED_LLM_MODELS or [])
        self.assertNotIn(RAGService()._rag_model, retired)


if __name__ == "__main__":
    unittest.main()
