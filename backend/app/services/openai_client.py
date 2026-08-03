from __future__ import annotations

from typing import Any


def create_async_openai_client(*, base_url: str | None = None, api_key: str) -> Any:
    """Load the optional OpenAI-compatible SDK only for a provider request."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=base_url, api_key=api_key)
