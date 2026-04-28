from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from typing import Iterable, Optional

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.services.intelligence import score_opportunity_match
from app.core.time import utc_now

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
EMBED_DIM = 192


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) > 1]


def _chunk_text(text: str, *, chunk_words: int = 110, overlap_words: int = 25) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_words - overlap_words)
    while start < len(words):
        chunk = " ".join(words[start : start + chunk_words]).strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def _hash_index(token: str, dim: int = EMBED_DIM) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % dim


def embed_text(text: str, *, dim: int = EMBED_DIM) -> list[float]:
    vector = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        idx = _hash_index(token, dim)
        vector[idx] += 1.0

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b))


def build_opportunity_chunks(opportunity: Opportunity) -> list[dict]:
    base_text = " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.opportunity_type or "",
            opportunity.domain or "",
            opportunity.university or "",
        ]
    ).strip()
    chunks = _chunk_text(base_text)
    if not chunks and base_text:
        chunks = [base_text]

    result: list[dict] = []
    for index, chunk in enumerate(chunks):
        result.append(
            {
                "source_type": "opportunity",
                "source_id": str(opportunity.id),
                "source_url": opportunity.url,
                "title": opportunity.title,
                "domain": opportunity.domain,
                "chunk_text": chunk,
                "chunk_index": index,
                "embedding": embed_text(chunk),
                "embedding_model": "hashing-v1",
                "updated_at": utc_now(),
            }
        )
    return result


async def upsert_opportunity_chunks(opportunity: Opportunity) -> int:
    if not opportunity.id:
        return 0

    source_id = str(opportunity.id)
    await KnowledgeChunk.find_many(
        KnowledgeChunk.source_type == "opportunity",
        KnowledgeChunk.source_id == source_id,
    ).delete()

    payloads = build_opportunity_chunks(opportunity)
    if not payloads:
        return 0

    docs = [KnowledgeChunk(**payload) for payload in payloads]
    await KnowledgeChunk.insert_many(docs)
    return len(docs)


async def rebuild_opportunity_index(*, limit: int = 2000, domain: Optional[str] = None) -> dict:
    safe_limit = max(1, min(limit, 10000))
    query = Opportunity.find_many(Opportunity.domain == domain) if domain else Opportunity.find_many()
    opportunities = await query.sort("-updated_at").limit(safe_limit).to_list()

    indexed_count = 0
    for opportunity in opportunities:
        indexed_count += await upsert_opportunity_chunks(opportunity)

    return {
        "indexed_sources": len(opportunities),
        "indexed_chunks": indexed_count,
        "domain_filter": domain,
    }


async def retrieve_chunks(query_text: str, *, top_k: int = 8, domain: Optional[str] = None) -> list[dict]:
    if not query_text.strip():
        return []

    query_embedding = embed_text(query_text)
    fetch_limit = max(50, min(top_k * 25, 2500))
    db_query = KnowledgeChunk.find_many(KnowledgeChunk.domain == domain) if domain else KnowledgeChunk.find_many()
    chunks = await db_query.sort("-updated_at").limit(fetch_limit).to_list()

    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        similarity = cosine_similarity(query_embedding, chunk.embedding)
        scored.append((similarity, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "similarity": round(item[0], 4),
            "chunk_id": str(item[1].id),
            "source_type": item[1].source_type,
            "source_id": item[1].source_id,
            "source_url": item[1].source_url,
            "title": item[1].title,
            "domain": item[1].domain,
            "chunk_text": item[1].chunk_text,
        }
        for item in scored[: max(1, top_k)]
    ]


def _profile_query(profile: Profile) -> str:
    return " ".join(
        [
            profile.skills or "",
            profile.interests or "",
            profile.education or "",
            profile.achievements or "",
            profile.bio or "",
        ]
    ).strip()


async def grounded_recommendations(
    profile: Profile,
    opportunities: Iterable[Opportunity],
    *,
    limit: int = 10,
) -> list[dict]:
    query_text = _profile_query(profile)
    if not query_text:
        return []

    retrieved = await retrieve_chunks(query_text, top_k=40)
    chunk_sim_by_opp: dict[str, float] = {}
    evidence_by_opp: dict[str, list[dict]] = {}

    for item in retrieved:
        source_id = item["source_id"]
        sim = float(item["similarity"])
        chunk_sim_by_opp[source_id] = max(chunk_sim_by_opp.get(source_id, 0.0), sim)
        evidence_by_opp.setdefault(source_id, []).append(
            {
                "similarity": sim,
                "title": item.get("title"),
                "source_url": item.get("source_url"),
                "chunk_text": item.get("chunk_text", "")[:260],
            }
        )

    ranked: list[dict] = []
    for opportunity in opportunities:
        heuristic_score, reasons = score_opportunity_match(profile, opportunity)
        rag_similarity = chunk_sim_by_opp.get(str(opportunity.id), 0.0)
        rag_points = min(45.0, rag_similarity * 100.0)
        final_score = round(min(100.0, heuristic_score * 0.65 + rag_points * 0.35), 2)

        evidence = sorted(
            evidence_by_opp.get(str(opportunity.id), []),
            key=lambda row: row["similarity"],
            reverse=True,
        )[:2]

        rationale = list(reasons)
        if evidence:
            rationale.append("Grounded by retrieved opportunity context chunks (RAG).")

        ranked.append(
            {
                "opportunity": opportunity,
                "match_score": final_score,
                "heuristic_score": round(heuristic_score, 2),
                "rag_similarity": round(rag_similarity, 4),
                "match_reasons": rationale,
                "evidence": evidence,
            }
        )

    ranked.sort(key=lambda item: item["match_score"], reverse=True)
    return ranked[: max(1, limit)]
