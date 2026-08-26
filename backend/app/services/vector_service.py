from __future__ import annotations

import asyncio
import json
import logging
from hashlib import md5
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import numpy as np
from beanie.odm.operators.find.comparison import In

from app.core.cache import cache_get_json, cache_key, cache_set_json
from app.models.opportunity import Opportunity
from app.models.vector_index_entry import VectorIndexEntry
from app.services.embedding_pipeline import embedding_pipeline
from app.services.embedding_service import embedding_service
from app.core.config import settings
from app.core import metrics as metrics_module
from app.core.time import as_utc_aware, utc_now

try:
    import faiss  # type: ignore
except Exception:
    faiss = None

logger = logging.getLogger(__name__)


def _opportunity_to_text(opportunity: Opportunity) -> str:
    return embedding_pipeline.opportunity_text(opportunity)


def _text_hash(text: str) -> str:
    return md5((text or "").encode("utf-8")).hexdigest()


async def _flush(model_cls, instances: list) -> int:
    """Persist accumulated rows in as few round trips as the backend allows.

    On Postgres this is a couple of executemany calls. With the ODM disabled
    there is no bulk path, so it falls back to the per-row saves this replaced.
    """
    if not instances:
        return 0
    if settings.POSTGRES_ODM_ENABLED:
        from app.db.pg_documents import bulk_save

        return await bulk_save(model_cls, instances)
    for instance in instances:
        if getattr(instance, "id", None) is None:
            await instance.insert()
        else:
            await instance.save()
    return len(instances)


async def _flush_in_batches(model_cls, instances: list, *, label: str) -> int:
    """Flush in committed chunks so a cancelled rebuild keeps what it finished.

    The rebuild used to accumulate every changed row and write it in a single
    _flush at the very end. That made the job all-or-nothing: it is run under a
    JOBS_HANDLER_TIMEOUT_SECONDS deadline, and when the deadline fired mid-write
    the whole batch was lost, so the next run recomputed exactly the same rows
    and lost them again. embeddings.rebuild died that way 93 times in a row -
    each attempt doing real work, none of it ever landing.

    Chunking does not make the work faster; it makes it cumulative. Every chunk
    that lands stays landed, so a run that only gets halfway leaves half the
    backlog permanently drained and the next run starts smaller.
    """
    if not instances:
        return 0
    size = max(1, int(getattr(settings, "VECTOR_FLUSH_BATCH_SIZE", 200)))
    written = 0
    for start in range(0, len(instances), size):
        chunk = instances[start : start + size]
        written += await _flush(model_cls, chunk)
        if len(instances) > size:
            logger.info(
                "vector rebuild: flushed %s/%s %s rows", written, len(instances), label
            )
    return written


class OpportunityVectorService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._index = None
        self._vectors: np.ndarray | None = None
        self._metas: list[dict[str, Any]] = []
        self._last_build_count = -1
        self._last_build_at: datetime | None = None
        self._ttl = timedelta(hours=max(1, int(settings.VECTOR_INDEX_STALE_HOURS)))

    def provider_name(self) -> str:
        if settings.MONGODB_ATLAS_VECTOR_SEARCH:
            return "atlas_vector_search"
        if faiss is not None:
            return "faiss"
        return "numpy_flat"

    def is_ready(self) -> bool:
        """Whether this process already has a usable in-memory opportunity index."""
        return self._last_build_at is not None

    def _score_to_similarity(self, score: float) -> float:
        return float(max(-1.0, min(1.0, score)))

    async def _sync_persistent_vectors(
        self,
        *,
        opportunities: list[Opportunity],
        texts: list[str],
    ) -> np.ndarray | None:
        # "mongo" is kept as an accepted value only because existing .env files
        # still say it; the rows now live in Postgres either way. "postgres" is
        # the honest name for the same behaviour.
        provider = (settings.VECTOR_STORE_PROVIDER or "memory").strip().lower()
        if provider not in ("mongo", "postgres") or not settings.VECTOR_STORE_PERSISTENCE_ENABLED:
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
        # Accumulated and written in bulk below. Saving each row as it is built
        # meant one round trip per row, and a full rebuild is thousands of them.
        pending_opportunities: list[Opportunity] = []
        pending_entries: list[VectorIndexEntry] = []

        for opportunity, text in zip(opportunities, texts):
            key = str(opportunity.id)
            text_hash = _text_hash(text)
            if (
                opportunity.embedding
                and opportunity.embedding_text_hash == text_hash
                and opportunity.embedding_model_version == embedding_pipeline.model_version
            ):
                embeddings_map[key] = list(opportunity.embedding)
                continue
            row = existing_map.get(key)
            if (
                row
                and row.text_hash == text_hash
                and row.embedding
                and row.metadata.get("embedding_model_version") == embedding_pipeline.model_version
            ):
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
                    "embedding_model_version": embedding_pipeline.model_version,
                    "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
                },
                "updated_at": now,
            }
            if (
                opportunity.embedding_text_hash != payload["text_hash"]
                or opportunity.embedding_model_version != embedding_pipeline.model_version
            ):
                opportunity.embedding = vector_values
                opportunity.embedding_text_hash = payload["text_hash"]
                opportunity.embedding_model_version = embedding_pipeline.model_version
                opportunity.embedding_updated_at = now
                pending_opportunities.append(opportunity)
            if row:
                # Only rewrite a row whose content actually moved. This branch
                # was unconditional, so every rebuild rewrote all ~1,850 entries
                # - each a 384-float array - even when nothing had changed. That
                # write storm is what made the API crawl while the rebuild job
                # was running: the same endpoint measured 64s during a rebuild
                # and 1.8s once it finished.
                #
                # `metadata` is deliberately not compared: it carries the
                # opportunity's updated_at, which the scraper touches constantly,
                # and matching on it would rewrite everything again for nothing.
                unchanged = (
                    row.text_hash == payload["text_hash"]
                    and row.embedding
                    and (row.metadata or {}).get("embedding_model_version")
                    == embedding_pipeline.model_version
                )
                if not unchanged:
                    row.text_hash = payload["text_hash"]
                    row.text = payload["text"]
                    row.embedding = payload["embedding"]
                    row.metadata = payload["metadata"]
                    row.updated_at = now
                    pending_entries.append(row)
            else:
                pending_entries.append(
                    VectorIndexEntry(
                        opportunity_id=opportunity.id,
                        text_hash=payload["text_hash"],
                        text=payload["text"],
                        embedding=payload["embedding"],
                        metadata=payload["metadata"],
                        updated_at=now,
                    )
                )

        await _flush_in_batches(Opportunity, pending_opportunities, label="opportunity")
        await _flush_in_batches(VectorIndexEntry, pending_entries, label="vector entry")

        # Remove entries for opportunities that no longer exist.
        try:
            collection_getter = getattr(VectorIndexEntry, "get_motor_collection", None) or getattr(
                VectorIndexEntry,
                "get_pymongo_collection",
            )
            collection = collection_getter()
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
            haystack = (
                f"{meta.get('title', '')} {meta.get('description', '')} "
                f"{meta.get('opportunity_type', '')}"
            ).lower()
            if not any(token in haystack for token in intent_tokens.get(intent, set())):
                return False

        locations = [value.lower() for value in filters.get("locations", []) if value]
        location = str(filters.get("location") or "").strip().lower()
        if location:
            locations.append(location)
        if locations:
            haystack = (
                f"{meta.get('title', '')} {meta.get('description', '')} "
                f"{meta.get('university', '')} {meta.get('location', '')}"
            ).lower()
            if not any(location in haystack for location in locations):
                return False

        work_mode = str(filters.get("work_mode") or "").strip().lower()
        if work_mode and work_mode != str(meta.get("work_mode") or "").strip().lower():
            return False

        opportunity_types = [value.lower() for value in filters.get("opportunity_types", []) if value]
        opportunity_type = str(filters.get("opportunity_type") or "").strip().lower()
        if opportunity_type:
            opportunity_types.append(opportunity_type)
        if opportunity_types and str(meta.get("opportunity_type") or "").strip().lower() not in opportunity_types:
            return False

        stipend_min = filters.get("stipend_min")
        if stipend_min is not None:
            try:
                required_stipend = int(stipend_min)
            except Exception:
                required_stipend = 0
            if required_stipend > 0 and int(meta.get("stipend_min") or 0) < required_stipend:
                return False

        tags = [value.lower() for value in filters.get("tags", []) if value]
        if tags:
            meta_tags = [str(value).lower() for value in list(meta.get("tags") or [])]
            if not any(tag in meta_tags for tag in tags):
                return False

        quality_min = filters.get("quality_min")
        if quality_min is not None:
            try:
                min_score = float(quality_min)
            except Exception:
                min_score = 0.0
            if min_score > 0 and float(meta.get("quality_score") or 0.0) < min_score:
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

    async def _ensure_index(self) -> None:
        """Index for a user request, without ever rebuilding inline.

        `rebuild` only short-circuits when the corpus count is unchanged, and
        the scraper adds rows continuously - so on a live system nearly every
        request found the count different and reloaded all ~1,880 rows, each
        carrying a 384-float embedding, then re-synced them. That is what made
        the feed take 98-143 seconds.

        A slightly stale index is the right trade here: the background
        `embeddings.rebuild` job already refreshes it, and a request should read
        whatever is current rather than pay to make it perfect.
        """
        if self.is_ready():
            # Deliberately no refresh from here, not even a background one:
            # kicking off a full rebuild per request just moved the same corpus
            # transfer off the critical path and into contention with it. The
            # scheduled `embeddings.rebuild` job owns refreshing.
            return
        # No index at all yet: this one request has to build it.
        await self.rebuild()

    def _schedule_background_refresh(self) -> None:
        task = getattr(self, "_refresh_task", None)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._refresh_task = loop.create_task(self._background_refresh())

    async def _background_refresh(self) -> None:
        try:
            await self.rebuild()
        except Exception:
            # A refresh failure must not surface on the request that triggered
            # it; the index simply stays as it was.
            pass

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

            # This is the one path that genuinely needs the embeddings; without
            # them every row would look unembedded and be recomputed on each
            # rebuild. with_vectors only exists on the Postgres query, so the
            # Beanie path is left alone.
            query = Opportunity.find_many()
            if hasattr(query, "with_vectors"):
                query = query.with_vectors()
            opportunities = await query.to_list()
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
                        "location": opportunity.location,
                        "work_mode": opportunity.work_mode,
                        "stipend_min": opportunity.stipend_min,
                        "tags": list(opportunity.tags or []),
                        "quality_score": opportunity.quality_score,
                        "embedding_model_version": opportunity.embedding_model_version,
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

    async def _atlas_search(
        self,
        query_vector: np.ndarray,
        *,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        collection_getter = getattr(Opportunity, "get_motor_collection", None) or getattr(
            Opportunity,
            "get_pymongo_collection",
        )
        collection = collection_getter()
        pipeline = [
            {
                "$vectorSearch": {
                    "index": settings.MONGODB_ATLAS_VECTOR_INDEX_NAME,
                    "path": "embedding",
                    "queryVector": [float(value) for value in query_vector.tolist()],
                    "numCandidates": max(100, top_k * 10),
                    "limit": max(top_k * 4, top_k),
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "title": 1,
                    "description": 1,
                    "url": 1,
                    "domain": 1,
                    "opportunity_type": 1,
                    "university": 1,
                    "deadline": 1,
                    "location": 1,
                    "work_mode": 1,
                    "stipend_min": 1,
                    "tags": 1,
                    "quality_score": 1,
                    "source": 1,
                    "created_at": 1,
                    "updated_at": 1,
                    "last_seen_at": 1,
                    "similarity": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        rows = await collection.aggregate(pipeline).to_list(length=max(top_k * 4, top_k))
        results: list[dict[str, Any]] = []
        for row in rows:
            meta = {
                "id": str(row.get("_id")),
                "title": row.get("title"),
                "description": row.get("description"),
                "url": row.get("url"),
                "domain": row.get("domain"),
                "opportunity_type": row.get("opportunity_type"),
                "university": row.get("university"),
                "deadline": row.get("deadline"),
                "location": row.get("location"),
                "work_mode": row.get("work_mode"),
                "stipend_min": row.get("stipend_min"),
                "tags": list(row.get("tags") or []),
                "quality_score": row.get("quality_score"),
                "source": row.get("source"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "last_seen_at": row.get("last_seen_at"),
                "similarity": round(self._score_to_similarity(float(row.get("similarity") or 0.0)), 6),
            }
            if not self._passes_filters(meta, filters):
                continue
            results.append(meta)
            if len(results) >= top_k:
                break
        return results

    async def search_by_vector(
        self,
        query_vector: np.ndarray,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_index()

        if not self._metas:
            return []

        safe_top_k = max(1, min(top_k, 200))
        query_vector = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(query_vector)
        if norm > 1e-12:
            query_vector = query_vector / norm

        if settings.MONGODB_ATLAS_VECTOR_SEARCH:
            try:
                return await self._atlas_search(query_vector, top_k=safe_top_k, filters=filters)
            except Exception:
                pass

        shortlist = min(max(safe_top_k * 4, 25), len(self._metas))

        if self._index is not None:
            scores, indices = self._index.search(query_vector.reshape(1, -1), shortlist)
            rank_items = list(zip(indices[0].tolist(), scores[0].tolist()))
        else:
            assert self._vectors is not None
            raw_scores = np.dot(self._vectors, query_vector)
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
        return results

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        await self._ensure_index()

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
                if metrics_module.CACHE_HITS_TOTAL is not None:
                    metrics_module.CACHE_HITS_TOTAL.labels(cache="vector_search").inc()
                return list(cached["results"])
            if metrics_module.CACHE_MISSES_TOTAL is not None:
                metrics_module.CACHE_MISSES_TOTAL.labels(cache="vector_search").inc()

        query_vector = await embedding_service.embed_query(query)
        results = await self.search_by_vector(query_vector, top_k=safe_top_k, filters=filters)

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
