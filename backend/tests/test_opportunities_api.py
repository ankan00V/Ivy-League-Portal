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
    def test_resolve_experiment_context_defaults_to_ranking_mode(self) -> None:
        experiment_key, experiment_variant = opportunities_endpoint._resolve_experiment_context(
            effective_mode="semantic",
            meta={},
        )
        self.assertEqual(experiment_key, "ranking_mode")
        self.assertEqual(experiment_variant, "semantic")

    def test_resolve_experiment_context_uses_meta_values(self) -> None:
        experiment_key, experiment_variant = opportunities_endpoint._resolve_experiment_context(
            effective_mode="ml",
            meta={"experiment_key": "ranking_mode_v2", "variant": "ml_canary"},
        )
        self.assertEqual(experiment_key, "ranking_mode_v2")
        self.assertEqual(experiment_variant, "ml_canary")

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

    async def test_log_opportunity_interaction_rejects_missing_tracking_metadata(self) -> None:
        user = DummyUser()
        payload = opportunities_endpoint.InteractionEventCreate(
            opportunity_id=PydanticObjectId("64b64b64b64b64b64b64b64c"),
            interaction_type="click",
        )

        with patch.object(opportunities_endpoint.Opportunity, "get", new=AsyncMock(return_value=object())):
            with self.assertRaises(opportunities_endpoint.HTTPException) as context:
                await opportunities_endpoint.log_opportunity_interaction(payload=payload, current_user=user)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Missing required tracking metadata", str(context.exception.detail))

    async def test_log_opportunity_interaction_normalizes_tracking_metadata(self) -> None:
        user = DummyUser()
        payload = opportunities_endpoint.InteractionEventCreate(
            opportunity_id=PydanticObjectId("64b64b64b64b64b64b64b64d"),
            interaction_type="click",
            ranking_mode=" Semantic ",
            experiment_key=" ranking_mode ",
            experiment_variant=" semantic ",
            rank_position=2,
        )

        with (
            patch.object(opportunities_endpoint.Opportunity, "get", new=AsyncMock(return_value=object())),
            patch.object(opportunities_endpoint.interaction_service, "log_event", new=AsyncMock()) as log_event,
        ):
            response = await opportunities_endpoint.log_opportunity_interaction(payload=payload, current_user=user)

        self.assertEqual(response["status"], "ok")
        log_event.assert_awaited_once()
        self.assertEqual(log_event.await_args.kwargs["ranking_mode"], "semantic")
        self.assertEqual(log_event.await_args.kwargs["experiment_key"], "ranking_mode")
        self.assertEqual(log_event.await_args.kwargs["experiment_variant"], "semantic")
        self.assertEqual(log_event.await_args.kwargs["rank_position"], 2)

    async def test_log_opportunity_interaction_rejects_simulated_traffic_type(self) -> None:
        user = DummyUser()
        payload = opportunities_endpoint.InteractionEventCreate(
            opportunity_id=PydanticObjectId("64b64b64b64b64b64b64b64e"),
            interaction_type="click",
            ranking_mode="semantic",
            experiment_key="ranking_mode",
            experiment_variant="semantic",
            rank_position=1,
            traffic_type="simulated",
        )

        with patch.object(opportunities_endpoint.Opportunity, "get", new=AsyncMock(return_value=object())):
            with self.assertRaises(opportunities_endpoint.HTTPException) as context:
                await opportunities_endpoint.log_opportunity_interaction(payload=payload, current_user=user)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("traffic_type must be 'real'", str(context.exception.detail))


if __name__ == "__main__":
    unittest.main()
