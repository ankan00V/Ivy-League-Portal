import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from beanie import PydanticObjectId

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import opportunities as opportunities_endpoint


class DummyUser:
    def __init__(self) -> None:
        self.id = PydanticObjectId("64b64b64b64b64b64b64b64b")


class TestOpportunitiesAPI(unittest.IsolatedAsyncioTestCase):
    async def test_ask_ai_shortlist_logs_telemetry(self) -> None:
        user = DummyUser()
        request = opportunities_endpoint.AskAIRequest(query="frontend internships", top_k=4)
        expected = {
            "request_id": "req-123",
            "query": request.query,
            "intent": {},
            "entities": {},
            "results": [],
            "insights": {
                "summary": "summary",
                "top_opportunities": [],
                "deadline_urgency": "soon",
                "recommended_action": "apply",
                "citations": [],
                "safety": {
                    "hallucination_checks_passed": True,
                    "failed_checks": [],
                    "quality_checks_passed": True,
                    "quality_failed_checks": [],
                    "judge_score": None,
                    "judge_rationale": None,
                },
                "contract_version": "rag_insights.v1",
            },
        }

        with (
            patch.object(opportunities_endpoint, "_get_or_create_profile", new=AsyncMock(return_value=object())),
            patch.object(opportunities_endpoint.rag_service, "ask", new=AsyncMock(return_value=expected)),
            patch.object(opportunities_endpoint.ranking_request_telemetry_service, "log", new=AsyncMock()) as telemetry_log,
        ):
            payload = await opportunities_endpoint.ask_ai_shortlist(request=request, current_user=user)

        self.assertEqual(payload["request_id"], "req-123")
        telemetry_log.assert_awaited()

    async def test_log_ask_ai_feedback_persists_event(self) -> None:
        user = DummyUser()
        payload = opportunities_endpoint.AskAIFeedbackRequest(
            request_id="req-123",
            query="frontend internships",
            feedback="up",
            response_summary="Strong shortlist",
            citations=[{"opportunity_id": "abc", "url": "https://example.com"}],
            surface="opportunities_page",
        )

        event_instance = type("DummyEvent", (), {"insert": AsyncMock()})()
        with patch.object(opportunities_endpoint, "RAGFeedbackEvent", return_value=event_instance) as event_cls:
            response = await opportunities_endpoint.log_ask_ai_feedback(payload=payload, current_user=user)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["feedback"], "up")
        event_cls.assert_called_once()
        event_instance.insert.assert_awaited()


if __name__ == "__main__":
    unittest.main()
