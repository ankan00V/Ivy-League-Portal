import os
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from openai import AsyncOpenAI
from app.api.deps import get_current_user
from app.models.user import User
from app.core.config import settings

router = APIRouter()

# Initialize AsyncOpenAI client configured for OpenRouter using Pydantic Settings
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_MODEL = settings.OPENROUTER_MODEL

if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY environment variable is missing. AI Chat will not function.")

# We MUST provide a fallback 'dummy' key so the AsyncOpenAI class itself doesn't crash on boot
# If the user doesn't have an API key, we handle the error inside the route handler instead of crashing the whole server
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY or "dummy_key_to_prevent_boot_crash",
)

class ChatMessage(BaseModel):
    role: str # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

class ChatResponse(BaseModel):
    message: str

SYSTEM_PROMPT = """
You are Vidya, the official, highly intelligent AI assistant for the VidyaVerse student opportunity tracking platform. 
Your tone should be encouraging, punchy, direct, and slightly brutalist like a high-tier hackathon mentor. 
You are deeply knowledgeable about career prep, competitive programming (Codebases, LeetCode, HackerRank), writing strong resumes, and networking.
Do NOT use overly flowery language. Give tactical, actionable advice.
When a student asks you a question, leverage your knowledge of top tech companies (Google, Meta, Stripe) to provide elite insights.
Use markdown for formatting. You can use emojis strategically, but keep them professional.
"""

@router.post("", response_model=ChatResponse, include_in_schema=False)
@router.post("/", response_model=ChatResponse)
async def chat_with_vidya(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    if not OPENROUTER_API_KEY:
         raise HTTPException(
             status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
             detail="Underlying AI service is not configured (Missing API Key)."
         )
         
    try:
        # Construct the message array including the System Prompt
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add user's context
        context_msg = f"[System Context: The current user interacting with you is named {current_user.full_name} ({current_user.email}).]"
        api_messages.append({"role": "system", "content": context_msg})
        
        # Append the historical conversation
        for msg in request.messages:
            if msg.role in ["user", "assistant"]:
                api_messages.append({"role": msg.role, "content": msg.content})
                
        response = await client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=api_messages,
            # OpenRouter optional headers for ranking
            extra_headers={
                "HTTP-Referer": "http://localhost:3000", # Optional
                "X-Title": "VidyaVerse AI", # Optional
            }
        )
        
        if response.choices and len(response.choices) > 0:
            ai_reply = response.choices[0].message.content
            return ChatResponse(message=ai_reply)
        else:
             raise HTTPException(status_code=500, detail="Empty response received from AI Model")
             
    except Exception as e:
        print(f"OpenRouter API Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate AI response. The service might be temporarily overloaded or the model may be unavailable."
        )
