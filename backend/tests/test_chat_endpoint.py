import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import chat as chat_endpoint


class TestChatEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_chat_endpoint_delegates_to_assistant_service(self) -> None:
        request = chat_endpoint.ChatRequest(
            messages=[chat_endpoint.ChatMessage(role="user", content="Find internships in NLP")],
            surface="global_chat",
        )
        fake_user = SimpleNamespace(id="u1", full_name="Test User", email="user@example.com")
        fake_profile = SimpleNamespace(user_id="u1")

        with (
            patch.object(chat_endpoint, "_get_profile", new=AsyncMock(return_value=fake_profile)),
            patch.object(
                chat_endpoint.assistant_service,
                "chat",
                new=AsyncMock(
                    return_value={
                        "request_id": "req_123",
                        "message": "Here are strong matches.",
                        "mode": "rag",
                        "citations": [{"opportunity_id": "opp1", "url": "https://example.com"}],
                    }
                ),
            ) as mock_chat,
        ):
            response = await chat_endpoint.chat_with_vidya(request=request, current_user=fake_user)

        self.assertEqual(response.request_id, "req_123")
        self.assertEqual(response.mode, "rag")
        self.assertEqual(response.message, "Here are strong matches.")
        self.assertEqual(len(response.citations), 1)
        mock_chat.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
