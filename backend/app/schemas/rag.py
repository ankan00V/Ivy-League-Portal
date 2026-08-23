from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RAGCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    title: Optional[str] = None
    source: Optional[str] = None


class RAGTopOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    why_fit: str = Field(min_length=1)
    urgency: Literal["low", "medium", "high"]
    match_score: float = Field(ge=0.0, le=100.0)
    citations: list[RAGCitation] = Field(default_factory=list, min_length=1)


class RAGSafetyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hallucination_checks_passed: bool = True
    failed_checks: list[str] = Field(default_factory=list)
    quality_checks_passed: bool = True
    quality_failed_checks: list[str] = Field(default_factory=list)
    judge_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    judge_rationale: Optional[str] = None


class RAGInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    top_opportunities: list[RAGTopOpportunity] = Field(default_factory=list, max_length=3)
    deadline_urgency: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    citations: list[RAGCitation] = Field(default_factory=list)
    safety: RAGSafetyReport = Field(default_factory=RAGSafetyReport)

    # Abstention is a first-class outcome, not an empty answer. Retrieval always
    # returns its nearest neighbours, so a query the corpus cannot answer still
    # produces a full shortlist; without these fields a caller cannot tell
    # "nothing relevant exists" from "here are the three best matches", and the
    # UI renders the least-bad rows as though they were an answer.
    abstained: bool = Field(default=False)
    abstain_reason: Optional[str] = None
    # Best cross-encoder score across the shortlist. Absolute, unlike cosine
    # similarity, which is why it can support a threshold at all.
    top_relevance_score: Optional[float] = None

    contract_version: str = Field(default="rag_insights.v1")


class RAGRetrievedOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: Optional[str] = None
    description: Optional[str] = None
    url: str = Field(min_length=1)
    domain: Optional[str] = None
    opportunity_type: Optional[str] = None
    university: Optional[str] = None
    deadline: Optional[datetime] = None
    similarity: Optional[float] = None
    source: Optional[str] = None


class RAGAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, Any] = Field(default_factory=dict)
    results: list[RAGRetrievedOpportunity] = Field(default_factory=list)
    insights: RAGInsights
    governance: dict[str, Any] = Field(default_factory=dict)
