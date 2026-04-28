import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from beanie import PydanticObjectId

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.assistant_service import assistant_service
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.assistant_memory_state import AssistantMemoryState


class TestAssistantService(unittest.IsolatedAsyncioTestCase):
    async def test_chat_routes_profile_tool(self) -> None:
        fake_user = SimpleNamespace(id="user-1", full_name="Test User", email="user@example.com")
        fake_profile = SimpleNamespace(
            user_type="student",
            domain="data science",
            skills="python, ml",
            education="B.Tech",
            goals=["internship"],
            resume_url="https://example.com/resume.pdf",
            interests="ai",
        )
        with (
            patch.object(assistant_service, "_persist_turns", new=AsyncMock()),
            patch.object(assistant_service, "_audit", new=AsyncMock()),
            patch("app.services.assistant_service.ranking_request_telemetry_service.log", new=AsyncMock()),
        ):
            result = await assistant_service.chat(
                user=fake_user,
                messages=[{"role": "user", "content": "Give me my profile summary"}],
                surface="global_chat",
                profile=fake_profile,
            )

        self.assertEqual(result["mode"], "tool")
        self.assertIn("Profile summary", result["message"])

    async def test_compact_memory_summarizes_old_turns(self) -> None:
        user_id = PydanticObjectId()
        rows = [
            SimpleNamespace(id=f"id-{index}", role="user" if index % 2 == 0 else "assistant", content=f"message-{index}")
            for index in range(18)
        ]
        find_chain = SimpleNamespace(sort=lambda *_: SimpleNamespace(to_list=AsyncMock(return_value=list(reversed(rows)))))
        delete_chain = SimpleNamespace(delete=AsyncMock())
        with (
            patch("app.services.assistant_service.settings.ASSISTANT_CHAT_SUMMARY_ENABLED", True),
            patch("app.services.assistant_service.settings.ASSISTANT_CHAT_SUMMARY_TRIGGER_TURNS", 10),
            patch("app.services.assistant_service.settings.ASSISTANT_CHAT_SUMMARY_RETAIN_TURNS", 4),
            patch.object(AssistantConversationTurn, "user_id", "user_id", create=True),
            patch.object(AssistantConversationTurn, "surface", "surface", create=True),
            patch.object(AssistantConversationTurn, "id", "id", create=True),
            patch.object(AssistantMemoryState, "user_id", "user_id", create=True),
            patch.object(AssistantMemoryState, "surface", "surface", create=True),
            patch("app.services.assistant_service.AssistantConversationTurn.find", side_effect=[find_chain, delete_chain]),
            patch("app.services.assistant_service.AssistantMemoryState.find_one", new=AsyncMock(return_value=None)),
            patch("app.services.assistant_service.AssistantMemoryState.insert", new=AsyncMock()) as mock_insert_state,
        ):
            await assistant_service._compact_memory(user_id=user_id, surface="global_chat")

        self.assertTrue(mock_insert_state.await_count >= 1)


if __name__ == "__main__":
    unittest.main()
