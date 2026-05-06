from __future__ import annotations

import asyncio
import json
from hashlib import md5
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import numpy as np
from beanie.odm.operators.find.comparison import In

from app.core.cache import cache_get_json, cache_key, cache_set_json
from app.models.opportunity import Opportunity
from app.models.vector_index_entry import VectorIndexEntry
from app.services.embedding_service import embedding_service
from app.core.config import settings
from app.core.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL
from app.core.time import as_utc_aware, utc_now

try:
    import faiss  # type: ignore
except Exception:
    faiss = None


def _opportunity_to_text(opportunity: Opportunity) -> str:
    return " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.domain or "",
            opportunity.opportunity_type or "",
            opportunity.university or "",
        ]
    ).strip()


def _text_hash(text: str) -> str:
    return md5((text or "").encode("utf-8")).hexdigest()


class OpportunityVectorService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._index = None
        self._vectors: np.ndarray | None = None
        self._metas: list[dict[str, Any]] = []
        self._last_build_count = -1
        self._last_build_at: datetime | None = None
        self._ttl = timedelta(minutes=5)

    def _score_to_similarity(self, score: float) -> float:
        return float(max(-1.0, min(1.0, score)))

    async def _sync_persistent_vectors(
        self,
        *,
        opportunities: list[Opportunity],
        texts: list[str],
    ) -> np.ndarray | None:
        provider = (settings.VECTOR_STORE_PROVIDER or "memory").strip().lower()
        if provider != "mongo" or not settings.VECTOR_STORE_PERSISTENCE_ENABLED:
            return None
        if not opportunities:
            return np.empty((0, embedding_service.dimension), dtype=np.float32)

        opp_ids = [opportunity.id for opportunity in opportunities]
        existing_rows = await VectorIndexEntry.find_many(In(VectorIndexEntry.opportunity_id, opp_ids)).to_list()
        existing_map = {str(row.opportunity_id): row for row in existing_rows}

        to_embed_texts: list[str] = []
        to_embed_keys: list[str] = []
        embeddings_map: dict[str, list[float]] = {}
        now = utc_now()

        for opportunity, text in zip(opportunities, texts):
            key = str(opportunity.id)
            text_hash = _text_hash(text)
            row = existing_map.get(key)
            if row and row.text_hash == text_hash and row.embedding:
                embeddings_map[key] = list(row.embedding)
                continue
            to_embed_keys.append(key)
            to_embed_texts.append(text)

        if to_embed_texts:
            embedded = await embedding_service.embed_texts(to_embed_texts)
            for idx, key in enumerate(to_embed_keys):
                vector = np.asarray(embedded[idx], dtype=np.float32)
                embeddings_map[key] = [float(value) for value in vector.tolist()]

        for opportunity, text in zip(opportunities, texts):
            key = str(opportunity.id)
            row = existing_map.get(key)
            vector_values = embeddings_map.get(key) or []
            if not vector_values:
                continue
            payload = {
                "text_hash": _text_hash(text),
                "text": text,
                "embedding": vector_values,
                "metadata": {
                    "title": opportunity.title,
                    "domain": opportunity.domain,
                    "opportunity_type": opportunity.opportunity_type,
                    "source": opportunity.source,
                    "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
                },
                "updated_at": now,
            }
            if row:
                row.text_hash = payload["text_hash"]
                row.text = payload["text"]
                row.embedding = payload["embedding"]
                row.metadata = payload["metadata"]
                row.updated_at = now
                await row.save()
            else:
                await VectorIndexEntry(
                    opportunity_id=opportunity.id,
                    text_hash=payload["text_hash"],
                    text=payload["text"],
                    embedding=payload["embedding"],
                    metadata=payload["metadata"],
                    updated_at=now,
                ).insert()

        # Remove entries for opportunities that no longer exist.
        try:
            collection = VectorIndexEntry.get_motor_collection()
            await collection.delete_many({"opportunity_id": {"$nin": opp_ids}})
        except Exception:
            pass

        vector_rows: list[np.ndarray] = []
        vector_dim: int | None = None
        for opportunity in opportunities:
            vector_values = embeddings_map.get(str(opportunity.id)) or []
            if not vector_values:
                return None
            array = np.asarray(vector_values, dtype=np.float32)
            if vector_dim is None:
                vector_dim = int(array.shape[0])
            if int(array.shape[0]) != int(vector_dim):
                return None
            vector_rows.append(array)

        if not vector_rows:
            return np.empty((0, embedding_service.dimension), dtype=np.float32)
        return np.vstack(vector_rows).astype(np.float32)

    def _passes_filters(self, meta: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True

        intent = filters.get("intent")
        if intent:
            intent_tokens = {
                "internships": {"internship", "job", "hiring", "intern"},
                "research": {"research", "fellowship", "assistant"},
                "scholarships": {"scholarship", "grant", "funding"},
                "hackathons": {"hackathon", "competition", "challenge"},
            }
            haystack = f"{meta.get('title', '')} {meta.get('description', '')} {meta.get('opportunity_type', '')}".lower()
            if not any(token in haystack for token in intent_tokens.get(intent, set())):
                return False

        locations = [value.lower() for value in filters.get("locations", []) if value]
        if locations:
            haystack = f"{meta.get('title', '')} {meta.get('description', '')} {meta.get('university', '')}".lower()
            if not any(location in haystack for location in locations):
                return False

        companies = [value.lower() for value in filters.get("companies", []) if value]
        if companies:
            haystack = f"{meta.get('title', '')} {meta.get('description', '')} {meta.get('university', '')}".lower()
            if not any(company in haystack for company in companies):
                return False

        max_deadline_days = filters.get("max_deadline_days")
        if isinstance(max_deadline_days, int):
            deadline = as_utc_aware(meta.get("deadline"))
            if deadline is None:
                return False
            days_left = (deadline - utc_now()).days
            if days_left > max_deadline_days:
                return False

        return True

    async def rebuild(self, force: bool = False) -> None:
        async with self._lock:
            now = utc_now()
            if (
                not force
                and self._last_build_at is not None
                and now - self._last_build_at <= self._ttl
            ):
                count = await Opportunity.find_many().count()
                if count == self._last_build_count:
                    return

            opportunities = await Opportunity.find_many().to_list()
            if not opportunities:
                self._vectors = np.empty((0, embedding_service.dimension), dtype=np.float32)
                self._metas = []
                self._index = None
                self._last_build_count = 0
                self._last_build_at = now
                return

            texts = [_opportunity_to_text(opportunity) for opportunity in opportunities]
            vectors = await self._sync_persistent_vectors(opportunities=opportunities, texts=texts)
            if vectors is None:
                vectors = await embedding_service.embed_texts(texts)
            vectors = np.asarray(vectors, dtype=np.float32)
            if vectors.ndim == 1:
                vectors = vectors.reshape(1, -1)

            metas = []
            for opportunity, text in zip(opportunities, texts):
                metas.append(
                    {
                        "id": str(opportunity.id),
                        "title": opportunity.title,
                        "description": opportunity.description,
                        "url": opportunity.url,
                        "domain": opportunity.domain,
                        "opportunity_type": opportunity.opportunity_type,
                        "university": opportunity.university,
                        "deadline": opportunity.deadline,
                        "source": opportunity.source,
                        "created_at": opportunity.created_at,
                        "updated_at": opportunity.updated_at,
                        "last_seen_at": opportunity.last_seen_at,
                        "text": text,
                    }
                )

            index = None
            if faiss is not None and len(vectors):
                index = faiss.IndexFlatIP(vectors.shape[1])
                index.add(vectors.astype(np.float32))

            self._vectors = vectors
            self._metas = metas
            self._index = index
            self._last_build_count = len(opportunities)
            self._last_build_at = now

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        await self.rebuild()

        if not self._metas:
            return []

        safe_top_k = max(1, min(top_k, 200))

        cache_enabled = bool(settings.CACHE_ENABLED and settings.CACHE_SEARCH_ENABLED)
        cache_version = ""
        if self._last_build_at is not None:
            cache_version = f"{self._last_build_at.isoformat()}:{self._last_build_count}"
        filter_key = ""
        try:
            filter_key = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
        except Exception:
            filter_key = str(filters or {})

        cache_key_value = cache_key(
            "vector_search",
            cache_version,
            str(safe_top_k),
            filter_key,
            (query or "").strip().lower(),
        )

        if cache_enabled:
            cached = await cache_get_json(cache_key_value)
            if cached and isinstance(cached.get("results"), list):
                if CACHE_HITS_TOTAL is not None:
                    CACHE_HITS_TOTAL.labels(cache="vector_search").inc()
                return list(cached["results"])
            if CACHE_MISSES_TOTAL is not None:
                CACHE_MISSES_TOTAL.labels(cache="vector_search").inc()

        query_vector = await embedding_service.embed_query(query)
        query_vector = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)

        shortlist = min(max(safe_top_k * 4, 25), len(self._metas))

        if self._index is not None:
            scores, indices = self._index.search(query_vector, shortlist)
            rank_items = list(zip(indices[0].tolist(), scores[0].tolist()))
        else:
            assert self._vectors is not None
            raw_scores = np.dot(self._vectors, query_vector[0])
            top_indices = np.argsort(-raw_scores)[:shortlist]
            rank_items = [(int(idx), float(raw_scores[idx])) for idx in top_indices]

        results: list[dict[str, Any]] = []
        for idx, score in rank_items:
            if idx < 0 or idx >= len(self._metas):
                continue
            meta = self._metas[idx]
            if not self._passes_filters(meta, filters):
                continue
            payload = dict(meta)
            payload["similarity"] = round(self._score_to_similarity(float(score)), 6)
            results.append(payload)
            if len(results) >= safe_top_k:
                break

        if cache_enabled:
            await cache_set_json(
                cache_key_value,
                {"results": results},
                ttl_seconds=int(settings.CACHE_SEARCH_TTL_SECONDS),
            )
        return results

    async def find_semantic_duplicates(
        self,
        text: str,
        *,
        threshold: float,
        top_k: int = 3,
        exclude_urls: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        excluded = {value for value in (exclude_urls or []) if value}
        candidates = await self.search(text, top_k=max(1, top_k * 3))
        deduped: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.get("url") in excluded:
                continue
            if float(candidate.get("similarity") or 0.0) >= threshold:
                deduped.append(candidate)
            if len(deduped) >= top_k:
                break
        return deduped


opportunity_vector_service = OpportunityVectorService()
