"""Cross-encoder reranking for RAG retrieval.

The bi-encoder retrieval path scores a query and an opportunity independently and
compares the two vectors, which is fast enough to scan the whole corpus but cannot
see how the two texts relate. That blind spot is visible in production: the query
"product and analytics competitions worth shortlisting this week" retrieved
"Codeforces Round 1117 (Div. 2)" at cosine 0.5, because a competitive-programming
contest and a product analytics competition occupy neighbouring regions of MiniLM
space. The generator then faithfully described a bad candidate list.

A cross-encoder reads the query and the document together and scores the pair
directly. On that exact failure it separates the two candidates by roughly twenty
logits, so reranking the bi-encoder's shortlist fixes the class of error rather
than the individual query.

Cost is why this is a second stage rather than the only one: the cross-encoder is
O(candidates) forward passes, so it reranks a shortlist of tens, never the corpus.

Every failure path returns the input order unchanged. A reranker that cannot load
must degrade to bi-encoder ordering, never to an empty shortlist - matching the
fallback chains the rest of this codebase uses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class RerankerService:
    def __init__(self) -> None:
        self._model: Any = None
        self._load_attempted = False
        self._load_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "RAG_RERANKER_ENABLED", True))

    def _model_name(self) -> str:
        return str(
            getattr(settings, "RAG_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        )

    async def _ensure_model(self) -> Any:
        """Load once. A failed load is remembered so every later query skips it."""
        if self._model is not None or self._load_attempted:
            return self._model

        async with self._load_lock:
            if self._model is not None or self._load_attempted:
                return self._model
            self._load_attempted = True
            try:
                from sentence_transformers import CrossEncoder

                name = self._model_name()
                self._model = await asyncio.to_thread(CrossEncoder, name, max_length=512)
                logger.info("Reranker loaded: %s", name)
            except Exception as exc:
                # Degrade to bi-encoder order rather than failing the request.
                logger.warning(
                    "Reranker unavailable (%s); serving bi-encoder ordering: %s",
                    self._model_name(),
                    exc,
                )
                self._model = None
        return self._model

    @staticmethod
    def _document_text(item: dict[str, Any]) -> str:
        """Title carries most of the signal; description disambiguates near-ties."""
        title = str(item.get("title") or "").strip()
        opportunity_type = str(item.get("opportunity_type") or "").strip()
        domain = str(item.get("domain") or "").strip()
        description = str(item.get("description") or "").strip()
        head = " | ".join(part for part in (title, opportunity_type, domain) if part)
        # 512-token model: leave room for the query rather than truncating mid-pair.
        return f"{head}\n{description}"[:1200]

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        limit = len(candidates) if top_k is None else max(1, int(top_k))
        if not self.enabled or len(candidates) < 2:
            return candidates[:limit]

        model = await self._ensure_model()
        if model is None:
            return candidates[:limit]

        pairs = [(query, self._document_text(item)) for item in candidates]
        try:
            scores = await asyncio.to_thread(model.predict, pairs)
        except Exception as exc:
            logger.warning("Reranker scoring failed; serving bi-encoder ordering: %s", exc)
            return candidates[:limit]

        # Fuse the two rankings instead of letting the cross-encoder overwrite the
        # bi-encoder's. Measured on this corpus, replacing the order outright was a
        # mixed result: it correctly dropped a Codeforces round from "product and
        # analytics competitions", but it also pushed "Machine Learning" and
        # "AI ML Intern" off the top of "machine learning internships in Bangalore"
        # in favour of "Graduate Trainee Engineer". ms-marco is trained on web
        # search passages, so it rewards queries whose phrasing matches the posting
        # ("final year students") over the domain term that actually matters.
        #
        # Reciprocal Rank Fusion combines the orderings by rank rather than score,
        # which is what makes it safe here: the two scorers live on different
        # scales (cosine in [0,1], cross-encoder logits in roughly [-11, +9]) and
        # no fixed weighting of the raw numbers transfers across queries. An item
        # must do well on at least one ranking and not badly on the other to reach
        # the top, so a confident cross-encoder rejection still demotes an off-topic
        # hit without discarding the domain match the bi-encoder found.
        k = float(getattr(settings, "RAG_RERANK_RRF_K", 60.0))

        bi_rank = {id(item): position for position, item in enumerate(candidates)}
        cross_order = sorted(
            range(len(candidates)), key=lambda i: float(scores[i]), reverse=True
        )
        cross_rank = {id(candidates[i]): position for position, i in enumerate(cross_order)}

        ranked: list[dict[str, Any]] = []
        for item, score in zip(candidates, scores):
            payload = dict(item)
            payload["rerank_score"] = round(float(score), 6)
            r_bi = bi_rank[id(item)]
            r_cross = cross_rank[id(item)]
            payload["rerank_rrf"] = round(1.0 / (k + r_bi) + 1.0 / (k + r_cross), 8)
            payload["rank_bi"] = r_bi
            payload["rank_cross"] = r_cross
            # similarity stays untouched: it is the bi-encoder's answer and is
            # persisted in telemetry. Overwriting it would silently redefine a
            # metric that other reports already compare across runs.
            ranked.append(payload)

        ranked.sort(key=lambda row: row.get("rerank_rrf", 0.0), reverse=True)
        return ranked[:limit]


reranker_service = RerankerService()
