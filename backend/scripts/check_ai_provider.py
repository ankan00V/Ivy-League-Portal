from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import AsyncOpenAI

from app.core.config import settings
from app.services.bedrock_llm_client import BedrockLLMClient, BedrockLLMConfig


async def _check_bedrock(timeout: float) -> dict[str, object]:
    client = BedrockLLMClient(
        BedrockLLMConfig(
            api_key=(settings.AWS_BEARER_TOKEN_BEDROCK or "").strip() or None,
            region=(settings.AWS_REGION or settings.AWS_DEFAULT_REGION or "us-east-1"),
            model_id=(settings.BEDROCK_MODEL_ID or "").strip(),
        )
    )
    if not client.is_configured:
        return {"ok": False, "provider": "bedrock", "detail": "missing Bedrock API key or model id"}
    content = await asyncio.wait_for(
        client.complete(
            model_id=(settings.BEDROCK_MODEL_ID or "").strip(),
            messages=[
                {"role": "user", "content": 'Return only this JSON: {"ok": true}'},
            ],
            temperature=0,
            max_tokens=20,
        ),
        timeout=timeout,
    )
    return {"ok": '"ok"' in content.lower(), "provider": "bedrock", "model": settings.BEDROCK_MODEL_ID}


async def _check_openai_compatible(timeout: float) -> dict[str, object]:
    api_key = (settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip()
    base_url = (
        (settings.LLM_API_BASE_URL or "").strip()
        or (settings.OPENROUTER_BASE_URL or "").strip()
        or "https://openrouter.ai/api/v1"
    )
    model = (
        (settings.RAG_LLM_MODEL or "").strip()
        or (settings.LLM_MODEL or "").strip()
        or (settings.OPENROUTER_MODEL or "").strip()
    )
    if not api_key:
        return {"ok": False, "provider": "openai_compatible", "detail": "missing API key"}
    if not model:
        return {"ok": False, "provider": "openai_compatible", "detail": "missing model"}

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": 'Return only this JSON: {"ok": true}'},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=20,
        ),
        timeout=timeout,
    )
    content = ""
    if response.choices and response.choices[0].message:
        content = response.choices[0].message.content or ""
    try:
        payload = json.loads(content)
    except Exception:
        payload = {}
    return {
        "ok": bool(payload.get("ok") is True),
        "provider": "openai_compatible",
        "base_url": base_url,
        "model": model,
    }


async def check(timeout: float) -> dict[str, object]:
    provider = str(settings.LLM_PROVIDER or "openai_compatible").strip().lower()
    try:
        if provider == "bedrock":
            return await _check_bedrock(timeout)
        return await _check_openai_compatible(timeout)
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "error": exc.__class__.__name__,
            "detail": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping the configured LLM provider without printing secrets.")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    result = asyncio.run(check(timeout=max(3.0, float(args.timeout))))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
