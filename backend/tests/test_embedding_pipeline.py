import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.embedding_pipeline import EmbeddingPipeline  # noqa: E402
from app.services.vector_service import OpportunityVectorService  # noqa: E402


class TestEmbeddingPipeline(unittest.TestCase):
    def test_opportunity_text_uses_rich_structured_representation(self) -> None:
        text = EmbeddingPipeline().opportunity_text(
            {
                "title": "Data Science Internship",
                "university": "Acme Labs",
                "opportunity_type": "Internship",
                "location": "Bangalore, India",
                "work_mode": "remote",
                "tags": ["python", "machine learning"],
                "description": "Build ranking experiments and model evaluation dashboards.",
            }
        )

        self.assertIn("[TITLE] Data Science Internship", text)
        self.assertIn("[COMPANY] Acme Labs", text)
        self.assertIn("[SKILLS] python, machine learning", text)
        self.assertIn("[DESC] Build ranking experiments", text)

    def test_vector_filters_apply_after_retrieval_metadata(self) -> None:
        service = OpportunityVectorService()
        meta = {
            "title": "ML Internship",
            "description": "Build production ML systems.",
            "university": "Acme",
            "location": "Bangalore, India",
            "work_mode": "remote",
            "opportunity_type": "Internship",
            "stipend_min": 25000,
            "tags": ["python", "mlops"],
            "quality_score": 84.0,
        }

        self.assertTrue(
            service._passes_filters(
                meta,
                {
                    "location": "Bangalore",
                    "work_mode": "remote",
                    "opportunity_types": ["internship"],
                    "stipend_min": 20000,
                    "tags": ["python"],
                    "quality_min": 30,
                },
            )
        )
        self.assertFalse(service._passes_filters(meta, {"work_mode": "onsite"}))
        self.assertFalse(service._passes_filters(meta, {"quality_min": 90}))


if __name__ == "__main__":
    unittest.main()
