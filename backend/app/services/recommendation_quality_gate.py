from __future__ import annotations

import statistics
import time
import re
from dataclasses import dataclass, field
from typing import Any

from beanie import PydanticObjectId

from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.services.recommendation_service import recommendation_service
from app.services.vector_service import opportunity_vector_service


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    profile: dict[str, Any]
    positive_terms: tuple[str, ...]
    top_k: int = 10
    min_relevant_in_top_k: int = 1
    min_mrr: float = 0.2


@dataclass(frozen=True)
class PersonaResult:
    name: str
    passed: bool
    latency_ms: float
    candidate_count: int
    returned_count: int
    relevant_in_top_k: int
    precision_at_k: float
    reciprocal_rank: float
    first_relevant_rank: int | None
    top_results: list[dict[str, Any]] = field(default_factory=list)


DEFAULT_PERSONAS: tuple[PersonaSpec, ...] = (
    PersonaSpec(
        name="ai_ml_engineering",
        profile={
            "first_name": "AI",
            "last_name": "Engineer",
            "user_type": "college_student",
            "domain": "AI/ML",
            "course": "B.Tech Computer Science",
            "bio": "Student building machine learning, ranking, NLP, and data products.",
            "skills": "python machine learning deep learning nlp data science ranking recommender systems",
            "interests": "AI internships research roles machine learning competitions",
            "domains_of_interest": ["AI/ML", "Data Science", "Software"],
            "career_intent": ["internship", "research", "fresher job"],
            "interest_graph": ["machine learning", "recommendation systems", "NLP"],
            "opportunity_types": ["Internship", "Job", "Hackathon"],
            "preferred_work_mode": "Remote",
            "work_preferences": ["remote", "hybrid"],
        },
        positive_terms=(
            "ai",
            "machine learning",
            "ml",
            "data science",
            "python",
            "model",
            "ranking",
            "recommender",
            "nlp",
            "analytics",
        ),
    ),
    PersonaSpec(
        name="frontend_product_engineering",
        profile={
            "first_name": "Frontend",
            "last_name": "Engineer",
            "user_type": "fresher",
            "domain": "Software",
            "course": "B.Tech Computer Science",
            "bio": "Frontend engineer focused on React, accessibility, UI systems, and product performance.",
            "skills": "react typescript javascript nextjs accessibility performance figma design systems",
            "interests": "frontend internships product engineering web performance",
            "domains_of_interest": ["Software", "Design", "Product"],
            "career_intent": ["internship", "fresher job"],
            "interest_graph": ["frontend", "react", "design systems"],
            "opportunity_types": ["Internship", "Job"],
            "preferred_work_mode": "Remote",
            "work_preferences": ["remote", "hybrid"],
        },
        positive_terms=(
            "frontend",
            "front-end",
            "react",
            "typescript",
            "javascript",
            "web",
            "ui",
            "design",
            "figma",
            "product",
        ),
    ),
    PersonaSpec(
        name="open_source_hackathon_builder",
        profile={
            "first_name": "Open",
            "last_name": "Source",
            "user_type": "college_student",
            "domain": "Software",
            "bio": "Student looking for GSoC, GSSoC, open-source programs, hackathons, and coding challenges.",
            "skills": "python javascript github open source api backend hackathon",
            "interests": "gsoc gssoc open source hackathons coding competitions devfolio devpost mlh",
            "domains_of_interest": ["Software", "Open Source", "Hackathons"],
            "career_intent": ["open source", "hackathon", "student program"],
            "interest_graph": ["gsoc", "open source", "hackathon"],
            "opportunity_types": ["Hackathon", "Competition", "Student Program"],
            "preferred_work_mode": "Remote",
            "work_preferences": ["remote"],
        },
        positive_terms=(
            "gsoc",
            "gssoc",
            "open source",
            "hackathon",
            "challenge",
            "competition",
            "github",
            "devfolio",
            "devpost",
            "mlh",
        ),
    ),
    PersonaSpec(
        name="remote_startup_intern",
        profile={
            "first_name": "Startup",
            "last_name": "Intern",
            "user_type": "college_student",
            "domain": "Software",
            "course": "B.Tech Computer Science",
            "bio": "Early-career student seeking remote startup internships and fresher software roles.",
            "skills": "python javascript backend frontend api sql startup",
            "interests": "remote internships startup jobs fresher software roles",
            "domains_of_interest": ["Software", "Startup", "Engineering"],
            "career_intent": ["internship", "fresher job"],
            "interest_graph": ["startup", "remote", "software internship"],
            "opportunity_types": ["Internship", "Job"],
            "preferred_work_mode": "Remote",
            "work_preferences": ["remote"],
        },
        positive_terms=(
            "intern",
            "internship",
            "remote",
            "startup",
            "fresher",
            "junior",
            "software",
            "developer",
            "engineer",
            "entry",
        ),
    ),
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_text(item) for item in value)
    return str(value).lower()


def opportunity_haystack(opportunity: Any) -> str:
    values = [
        getattr(opportunity, "title", ""),
        getattr(opportunity, "description", ""),
        getattr(opportunity, "domain", ""),
        getattr(opportunity, "opportunity_type", ""),
        getattr(opportunity, "portal_category", ""),
        getattr(opportunity, "university", ""),
        getattr(opportunity, "source", ""),
        getattr(opportunity, "location", ""),
        getattr(opportunity, "work_mode", ""),
        getattr(opportunity, "eligibility", ""),
        getattr(opportunity, "tags", []),
    ]
    return " ".join(_normalize_text(value) for value in values)


def is_relevant_for_persona(opportunity: Any, persona: PersonaSpec) -> bool:
    haystack = opportunity_haystack(opportunity)
    for raw_term in persona.positive_terms:
        term = raw_term.lower().strip()
        if not term:
            continue
        if len(term) <= 3 and term.replace("#", "").isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
                return True
            continue
        if term in haystack:
            return True
    return False


def summarize_ranked_results(
    *,
    persona: PersonaSpec,
    ranked: list[dict[str, Any]],
    latency_ms: float,
    candidate_count: int,
) -> PersonaResult:
    top_k = max(1, int(persona.top_k))
    top_items = ranked[:top_k]
    relevant_ranks: list[int] = []
    top_results: list[dict[str, Any]] = []

    for index, item in enumerate(top_items, start=1):
        opportunity = item.get("opportunity")
        relevant = is_relevant_for_persona(opportunity, persona)
        if relevant:
            relevant_ranks.append(index)
        top_results.append(
            {
                "rank": index,
                "id": str(getattr(opportunity, "id", "")),
                "title": getattr(opportunity, "title", ""),
                "source": getattr(opportunity, "source", None),
                "domain": getattr(opportunity, "domain", None),
                "type": getattr(opportunity, "opportunity_type", None),
                "match_score": item.get("match_score"),
                "ranking_mode": item.get("ranking_mode"),
                "relevant": relevant,
            }
        )

    first_rank = relevant_ranks[0] if relevant_ranks else None
    reciprocal_rank = round(1.0 / first_rank, 6) if first_rank else 0.0
    relevant_in_top_k = len(relevant_ranks)
    precision_at_k = round(relevant_in_top_k / float(top_k), 6)
    passed = relevant_in_top_k >= persona.min_relevant_in_top_k and reciprocal_rank >= float(persona.min_mrr)

    return PersonaResult(
        name=persona.name,
        passed=passed,
        latency_ms=round(float(latency_ms), 3),
        candidate_count=int(candidate_count),
        returned_count=len(ranked),
        relevant_in_top_k=relevant_in_top_k,
        precision_at_k=precision_at_k,
        reciprocal_rank=reciprocal_rank,
        first_relevant_rank=first_rank,
        top_results=top_results,
    )


def aggregate_persona_results(
    *,
    results: list[PersonaResult],
    min_persona_pass_rate: float = 0.75,
    min_mean_mrr: float = 0.35,
    max_p95_latency_ms: float = 1500.0,
) -> dict[str, Any]:
    if not results:
        return {
            "ready": False,
            "persona_count": 0,
            "pass_rate": 0.0,
            "mean_mrr": 0.0,
            "p95_latency_ms": 0.0,
            "gates": [
                {"name": "personas_present", "pass": False, "detail": "no personas evaluated"},
            ],
        }

    pass_rate = sum(1 for item in results if item.passed) / float(len(results))
    mean_mrr = statistics.mean(item.reciprocal_rank for item in results)
    latencies = sorted(item.latency_ms for item in results)
    latency_index = min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))
    p95_latency_ms = latencies[latency_index]

    gates = [
        {
            "name": "persona_pass_rate",
            "pass": pass_rate >= float(min_persona_pass_rate),
            "detail": f"pass_rate={pass_rate:.3f}, min={float(min_persona_pass_rate):.3f}",
        },
        {
            "name": "mean_reciprocal_rank",
            "pass": mean_mrr >= float(min_mean_mrr),
            "detail": f"mean_mrr={mean_mrr:.3f}, min={float(min_mean_mrr):.3f}",
        },
        {
            "name": "p95_latency",
            "pass": p95_latency_ms <= float(max_p95_latency_ms),
            "detail": f"p95_latency_ms={p95_latency_ms:.3f}, max={float(max_p95_latency_ms):.3f}",
        },
    ]

    return {
        "ready": all(gate["pass"] for gate in gates),
        "persona_count": len(results),
        "pass_rate": round(pass_rate, 6),
        "mean_mrr": round(mean_mrr, 6),
        "p95_latency_ms": round(float(p95_latency_ms), 3),
        "gates": gates,
    }


async def run_live_recommendation_quality_gate(
    *,
    opportunities: list[Opportunity],
    ranking_mode: str = "ml",
    limit: int = 20,
    personas: tuple[PersonaSpec, ...] = DEFAULT_PERSONAS,
    warmup: bool = True,
) -> list[PersonaResult]:
    results: list[PersonaResult] = []
    candidate_count = len(opportunities)

    if warmup and opportunities:
        try:
            await opportunity_vector_service.search(
                "recommendation quality gate warmup",
                top_k=1,
            )
        except Exception:
            # The recommendation service itself has semantic fallbacks. The gate
            # should still evaluate serving behavior when warmup is unavailable.
            pass

    for persona in personas:
        profile = Profile(user_id=PydanticObjectId(), **persona.profile)
        query = " ".join(
            [
                str(profile.skills or ""),
                str(profile.interests or ""),
                " ".join(profile.interest_graph or []),
                " ".join(profile.career_intent or []),
            ]
        ).strip()
        started = time.perf_counter()
        ranked, _meta = await recommendation_service.rank(
            user_id=profile.user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(limit, persona.top_k),
            min_score=0.0,
            ranking_mode=ranking_mode,
            query=query,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        results.append(
            summarize_ranked_results(
                persona=persona,
                ranked=ranked,
                latency_ms=elapsed_ms,
                candidate_count=candidate_count,
            )
        )

    return results
