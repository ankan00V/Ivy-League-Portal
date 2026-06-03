import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from beanie import PydanticObjectId
from datetime import datetime, timedelta, timezone

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

    def test_opportunity_freshness_accepts_naive_mongo_datetimes(self) -> None:
        opportunity = type(
            "OpportunityStub",
            (),
            {
                "last_seen_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
                "updated_at": None,
                "created_at": None,
            },
        )()

        freshness = opportunities_endpoint._freshness_seconds([opportunity])

        self.assertIsNotNone(freshness)
        self.assertGreaterEqual(freshness or 0.0, 0.0)

    def test_opportunity_sort_key_accepts_mixed_datetime_awareness(self) -> None:
        naive = type(
            "OpportunityStub",
            (),
            {
                "last_seen_at": datetime(2026, 5, 6, 4, 0),
                "updated_at": None,
                "created_at": datetime(2026, 5, 6, 3, 0, tzinfo=timezone.utc),
            },
        )()
        aware = type(
            "OpportunityStub",
            (),
            {
                "last_seen_at": datetime(2026, 5, 6, 5, 0, tzinfo=timezone.utc),
                "updated_at": None,
                "created_at": datetime(2026, 5, 6, 2, 0),
            },
        )()

        sorted([naive, aware], key=opportunities_endpoint._activity_sort_key, reverse=True)

    async def test_trigger_scraper_enqueues_for_authenticated_user(self) -> None:
        user = DummyUser()
        job = type("JobStub", (), {"id": PydanticObjectId("64b64b64b64b64b64b64b64c")})()

        with (
            patch.object(opportunities_endpoint.settings, "JOBS_ENABLED", True),
            patch("app.services.scraper.get_scraper_runtime_status", return_value={"is_running": False}),
            patch("app.services.job_runner.job_runner.enqueue", new=AsyncMock(return_value=job)) as enqueue,
        ):
            payload = await opportunities_endpoint.trigger_scraper(user)

        enqueue.assert_awaited_once()
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["message"], "Scraper job enqueued.")

    async def test_read_scraper_health_exposes_per_source_runtime(self) -> None:
        runtime = {
            "is_running": False,
            "last_status": "partial_success",
            "consecutive_failures": 0,
            "last_started_at": "2026-05-08T05:00:00+00:00",
            "last_finished_at": "2026-05-08T05:02:00+00:00",
            "last_successful_at": "2026-05-08T05:02:00+00:00",
            "auto_update": {"enabled": True},
            "last_report": {
                "sources": [
                    {"source": "unstop", "fetched": 10, "inserted": 2, "updated": 3, "failed": 0, "errors": []},
                    {"source": "linkedin", "fetched": 4, "inserted": 0, "updated": 0, "failed": 4, "errors": ["403"]},
                ]
            },
        }

        with patch("app.services.scraper.get_scraper_runtime_status", return_value=runtime):
            payload = await opportunities_endpoint.read_scraper_health()

        self.assertEqual(payload.last_status, "partial_success")
        self.assertEqual(len(payload.sources), 2)
        self.assertEqual(payload.sources[0].status, "ok")
        self.assertEqual(payload.sources[1].status, "error")
        self.assertEqual(payload.sources[1].errors, ["403"])

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

    async def test_log_opportunity_interactions_batch_validates_before_writing(self) -> None:
        user = DummyUser()
        payload = opportunities_endpoint.InteractionBatchCreate(
            events=[
                opportunities_endpoint.InteractionEventCreate(
                    opportunity_id=PydanticObjectId("64b64b64b64b64b64b64b650"),
                    interaction_type="click",
                    ranking_mode="semantic",
                    experiment_key="ranking_mode",
                    experiment_variant="semantic",
                    rank_position=1,
                ),
                opportunities_endpoint.InteractionEventCreate(
                    opportunity_id=PydanticObjectId("64b64b64b64b64b64b64b651"),
                    interaction_type="shortlisted",
                    ranking_mode="semantic",
                    experiment_key="ranking_mode",
                    experiment_variant="semantic",
                    rank_position=2,
                ),
            ]
        )

        with (
            patch.object(opportunities_endpoint.Opportunity, "get", new=AsyncMock(return_value=object())),
            patch.object(opportunities_endpoint.interaction_service, "log_event", new=AsyncMock()) as log_event,
        ):
            with self.assertRaises(opportunities_endpoint.HTTPException) as context:
                await opportunities_endpoint.log_opportunity_interactions_batch(payload=payload, current_user=user)

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Invalid interaction_type")
        log_event.assert_not_awaited()

    def test_recommended_response_includes_trust_metadata(self) -> None:
        opportunity = type(
            "OpportunityRow",
            (),
            {
                "id": PydanticObjectId("64b64b64b64b64b64b64b64f"),
                "title": "Verified opportunity",
                "description": "Official opportunity from a known organizer.",
                "url": "https://devfolio.co/example",
                "opportunity_type": "Hackathon",
                "university": "Devfolio",
                "portal_category": "competitive",
                "deadline": None,
                "domain": "engineering",
                "source": "devfolio",
                "canonical_key": "devfolio::verified-opportunity::hackathon",
                "location": "Remote",
                "work_mode": "Remote",
                "stipend": "INR 25000 / month",
                "eligibility": "2026 batch students",
                "batch_years": [2026],
                "ppo_available": "Available",
                "trust_status": "verified",
                "trust_score": 88,
                "risk_score": 12,
                "risk_reasons": [],
                "verification_evidence": ["trusted host"],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "last_seen_at": datetime.now(timezone.utc),
            },
        )()
        payload = opportunities_endpoint._to_recommended_response(
            {
                "opportunity": opportunity,
                "match_score": 72.0,
                "match_reasons": ["Strong fit"],
            }
        )
        self.assertEqual(payload.trust_status, "verified")
        self.assertEqual(payload.trust_score, 88)
        self.assertEqual(payload.location, "Remote")
        self.assertEqual(payload.batch_years, [2026])


if __name__ == "__main__":
    unittest.main()
