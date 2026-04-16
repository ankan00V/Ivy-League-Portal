from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
import re
import struct
from typing import Iterable

import numpy as np
from openai import AsyncOpenAI

from app.core.cache import cache_get_bytes, cache_key, cache_set_bytes
from app.core.config import settings
from app.core.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Embedding provider with local sentence-transformers as primary option.
    Falls back to OpenAI embeddings or a deterministic hash embedding.
    """

    def __init__(self) -> None:
        self.provider = (settings.EMBEDDING_PROVIDER or "sentence_transformers").strip().lower()
        self.local_model_name = settings.EMBEDDING_MODEL
        self.openai_model = settings.OPENAI_EMBEDDING_MODEL
        self._local_model = None
        self._label_dim = 384
        self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
        self._local_model_disabled = False
        self._local_model_failure_logged = False

    @property
    def dimension(self) -> int:
        return self._label_dim

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        if vectors.size == 0:
            return vectors
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.clip(norms, 1e-12, None)
        return vectors / norms

    def _ensure_local_model(self):
        if self._local_model_disabled:
            raise RuntimeError("Local sentence-transformers model is disabled due to previous init failure.")

        if self._local_model is not None:
            return self._local_model

        try:
            from huggingface_hub.utils import disable_progress_bars

            disable_progress_bars()
        except Exception:
            pass

        try:
            from transformers.utils import logging as transformers_logging

            transformers_logging.set_verbosity_error()
        except Exception:
            pass

        from sentence_transformers import SentenceTransformer

        # Model initialization can emit verbose progress / advisory output; keep startup logs clean.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self._local_model = SentenceTransformer(self.local_model_name)
        return self._local_model

    def _hash_embed_text(self, text: str) -> np.ndarray:
        vector = np.zeros(self._label_dim, dtype=np.float32)
        tokens = TOKEN_PATTERN.findall((text or "").lower())
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest, 16) % self._label_dim
            vector[idx] += 1.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def embed_texts_sync(self, texts: Iterable[str]) -> np.ndarray:
        values = [value or "" for value in texts]
        if not values:
            return np.empty((0, self._label_dim), dtype=np.float32)

        if self.provider in {"sentence_transformers", "auto"}:
            try:
                model = self._ensure_local_model()
                vectors = model.encode(
                    values,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                vectors = np.asarray(vectors, dtype=np.float32)
                if vectors.ndim == 1:
                    vectors = vectors.reshape(1, -1)
                self._label_dim = int(vectors.shape[1])
                return vectors
            except Exception as exc:
                self._local_model_disabled = True
                if not self._local_model_failure_logged:
                    logger.warning(
                        "[EmbeddingService] sentence-transformers unavailable; falling back to hash embedding: %s",
                        exc,
                    )
                    self._local_model_failure_logged = True

        vectors = np.asarray([self._hash_embed_text(value) for value in values], dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        return self._normalize(vectors)

    async def embed_texts(self, texts: Iterable[str]) -> np.ndarray:
        values = [value or "" for value in texts]
        if not values:
            return np.empty((0, self._label_dim), dtype=np.float32)

        if self.provider == "openai" and self._openai_client:
            try:
                response = await self._openai_client.embeddings.create(
                    model=self.openai_model,
                    input=values,
                )
                vectors = np.asarray([row.embedding for row in response.data], dtype=np.float32)
                vectors = self._normalize(vectors)
                if vectors.ndim == 1:
                    vectors = vectors.reshape(1, -1)
                self._label_dim = int(vectors.shape[1])
                return vectors
            except Exception as exc:
                print(f"[EmbeddingService] OpenAI embeddings failed, falling back to local/hash: {exc}")

        return await asyncio.to_thread(self.embed_texts_sync, values)

    async def embed_text(self, text: str) -> np.ndarray:
        vectors = await self.embed_texts([text])
        return vectors[0] if len(vectors) else np.zeros((self._label_dim,), dtype=np.float32)

    async def embed_query(self, text: str) -> np.ndarray:
        """
        Cached embeddings for short user queries.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return np.zeros((self._label_dim,), dtype=np.float32)

        if (
            not settings.CACHE_ENABLED
            or not settings.CACHE_EMBEDDINGS_ENABLED
            or len(cleaned) > int(settings.CACHE_MAX_TEXT_LENGTH)
        ):
            return await self.embed_text(cleaned)

        key = cache_key(
            "embedding",
            self.provider,
            self.local_model_name,
            self.openai_model,
            cleaned.lower(),
        )
        cached = await cache_get_bytes(key)
        if cached:
            try:
                (dim,) = struct.unpack("<I", cached[:4])
                vector = np.frombuffer(cached[4:], dtype=np.float32, count=int(dim))
                if vector.size == int(dim):
                    if CACHE_HITS_TOTAL is not None:
                        CACHE_HITS_TOTAL.labels(cache="embedding").inc()
                    return vector
            except Exception:
                pass

        if CACHE_MISSES_TOTAL is not None:
            CACHE_MISSES_TOTAL.labels(cache="embedding").inc()

        vector = await self.embed_text(cleaned)
        try:
            payload = struct.pack("<I", int(vector.size)) + vector.astype(np.float32, copy=False).tobytes()
            await cache_set_bytes(
                key,
                payload,
                ttl_seconds=int(settings.CACHE_EMBEDDING_TTL_SECONDS),
            )
        except Exception:
            pass
        return vector


embedding_service = EmbeddingService()
