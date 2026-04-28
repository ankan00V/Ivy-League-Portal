from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Any, List, Optional
from app.api.deps import get_current_user
from app.models.profile import Profile
from app.models.user import User
from app.services.assistant_service import assistant_service

router = APIRouter()

class ChatMessage(BaseModel):
    role: str # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    surface: str = "global_chat"

class ChatResponse(BaseModel):
    request_id: str
    message: str
    mode: str
    citations: List[dict[str, Any]] = []


async def _get_profile(user_id) -> Profile | None:
    return await Profile.find_one(Profile.user_id == user_id)

@router.post("", response_model=ChatResponse, include_in_schema=False)
@router.post("/", response_model=ChatResponse)
async def chat_with_vidya(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        profile = await _get_profile(current_user.id)
        result = await assistant_service.chat(
            user=current_user,
            messages=[message.model_dump() for message in request.messages],
            surface=(request.surface or "global_chat").strip() or "global_chat",
            profile=profile,
        )
        return ChatResponse(
            request_id=str(result.get("request_id") or ""),
            message=str(result.get("message") or ""),
            mode=str(result.get("mode") or "general"),
            citations=list(result.get("citations") or []),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as e:
        print(f"LLM API Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate AI response. The service might be temporarily overloaded or the model may be unavailable."
        )
