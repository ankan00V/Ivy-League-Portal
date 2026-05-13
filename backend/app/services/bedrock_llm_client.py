from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BedrockLLMConfig:
    api_key: str | None
    region: str
    model_id: str


class BedrockLLMClient:
    def __init__(self, config: BedrockLLMConfig) -> None:
        self._config = config
        self._client: Any | None = None
        if config.api_key and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = config.api_key

    @property
    def is_configured(self) -> bool:
        return bool((self._config.api_key or "").strip() and (self._config.model_id or "").strip())

    def _runtime_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # type: ignore
            except Exception as exc:  # pragma: no cover - dependency is declared in requirements
                raise RuntimeError("boto3 is required for Amazon Bedrock LLM requests.") from exc
            self._client = boto3.client("bedrock-runtime", region_name=self._config.region)
        return self._client

    def _to_converse_payload(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        system: list[dict[str, str]] = []
        conversation: list[dict[str, Any]] = []
        for item in messages:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                system.append({"text": content})
            elif role in {"assistant", "user"}:
                conversation.append({"role": role, "content": [{"text": content}]})

        if not conversation:
            conversation.append({"role": "user", "content": [{"text": "Respond with a concise answer."}]})
        return system, conversation

    def _extract_text(self, response: dict[str, Any]) -> str:
        output = response.get("output") or {}
        message = output.get("message") or {}
        chunks = message.get("content") or []
        text_parts = [str(chunk.get("text") or "") for chunk in chunks if isinstance(chunk, dict)]
        return "\n".join(part.strip() for part in text_parts if part.strip()).strip()

    def _complete_sync(
        self,
        *,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.is_configured:
            raise RuntimeError("Amazon Bedrock is not configured.")
        system, conversation = self._to_converse_payload(messages)
        request: dict[str, Any] = {
            "modelId": (model_id or self._config.model_id).strip(),
            "messages": conversation,
        }
        if system:
            request["system"] = system
        inference_config: dict[str, Any] = {}
        if temperature is not None:
            inference_config["temperature"] = float(temperature)
        if max_tokens is not None:
            inference_config["maxTokens"] = int(max_tokens)
        if inference_config:
            request["inferenceConfig"] = inference_config

        response = self._runtime_client().converse(**request)
        text = self._extract_text(response)
        if not text:
            raise RuntimeError("Empty response received from Amazon Bedrock.")
        return text

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._complete_sync,
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
