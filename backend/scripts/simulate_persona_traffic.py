from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from beanie import PydanticObjectId, init_beanie
from beanie.odm.operators.find.comparison import In
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.application import Application
from app.models.experiment import Experiment, ExperimentAssignment, ExperimentVariant
from app.models.model_drift_report import ModelDriftReport
from app.models.nlp_model_version import NLPModelVersion
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.otp_code import OTPCode
from app.models.post import Comment, Post
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.vector_index_entry import VectorIndexEntry
from app.models.user import User
from app.services.experiment_analytics_service import experiment_analytics_service
from app.services.experiment_service import experiment_service
from app.services.recommendation_service import recommendation_service


INDIAN_CITIES = [
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Mumbai",
    "Delhi",
    "Noida",
    "Gurugram",
    "Chennai",
    "Ahmedabad",
    "Kolkata",
    "Jaipur",
    "Indore",
    "Kochi",
    "Bhubaneswar",
    "Lucknow",
]

FIRST_NAMES = [
    "Aarav",
    "Vihaan",
    "Aditya",
    "Arjun",
    "Ishaan",
    "Reyansh",
    "Rohan",
    "Karthik",
    "Pranav",
    "Ananya",
    "Diya",
    "Aditi",
    "Meera",
    "Isha",
    "Saanvi",
    "Kavya",
    "Ritika",
    "Nandini",
]

LAST_NAMES = [
    "Sharma",
    "Patel",
    "Gupta",
    "Singh",
    "Reddy",
    "Iyer",
    "Nair",
    "Chatterjee",
    "Ghosh",
    "Jain",
    "Kulkarni",
    "Yadav",
    "Mishra",
    "Bansal",
    "Agarwal",
    "Verma",
]

PERSONA_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "ai_ml_builder",
        "skills": ["Python", "PyTorch", "TensorFlow", "NLP", "LLMs", "RAG", "MLOps", "FastAPI"],
        "interests": ["AI internships", "ML research", "GenAI hackathons", "NLP challenges"],
        "education": ["B.Tech CSE", "B.E. AI/DS", "M.Tech AI"],
        "queries": [
            "ai internship nlp llm rag",
            "machine learning internship python remote",
            "genai hackathon india",
        ],
        "preferred_types": {"internship", "research", "competition"},
        "preferred_domains": {"ai", "machine learning", "data"},
    },
    {
        "name": "data_analyst_track",
        "skills": ["SQL", "Excel", "Power BI", "Tableau", "Python", "Statistics", "A/B Testing"],
        "interests": ["Data analyst internships", "BI challenges", "Analytics scholarships"],
        "education": ["BBA Analytics", "B.Sc Statistics", "B.Tech IT"],
        "queries": [
            "data analyst internship sql power bi",
            "business analytics internship india",
            "data science fellowship students",
        ],
        "preferred_types": {"internship", "scholarship"},
        "preferred_domains": {"data", "analytics", "science"},
    },
    {
        "name": "backend_engineer_track",
        "skills": ["Python", "FastAPI", "Django", "PostgreSQL", "Docker", "Redis", "System Design"],
        "interests": ["Backend internships", "API engineering", "Cloud roles"],
        "education": ["B.Tech CSE", "B.Tech IT", "MCA"],
        "queries": [
            "backend internship python fastapi",
            "software engineering internship remote india",
            "cloud devops internship docker kubernetes",
        ],
        "preferred_types": {"internship", "job"},
        "preferred_domains": {"engineering", "software", "cloud"},
    },
    {
        "name": "frontend_product_track",
        "skills": ["React", "Next.js", "TypeScript", "Figma", "Product Thinking", "UI/UX"],
        "interests": ["Frontend internships", "Product design challenges", "Hackathons"],
        "education": ["B.Des", "B.Tech CSE", "BCA"],
        "queries": [
            "frontend internship react nextjs",
            "ui ux hackathon india",
            "product internship startup india",
        ],
        "preferred_types": {"internship", "competition", "workshop"},
        "preferred_domains": {"engineering", "design", "product"},
    },
    {
        "name": "cybersec_track",
        "skills": ["Network Security", "Burp Suite", "OWASP", "Linux", "Python", "SIEM"],
        "interests": ["Cybersecurity internships", "CTFs", "Security research roles"],
        "education": ["B.Tech CSE", "B.Sc Cyber Security", "MCA"],
        "queries": [
            "cyber security internship india",
            "ctf hackathon student",
            "vulnerability assessment internship",
        ],
        "preferred_types": {"internship", "competition", "research"},
        "preferred_domains": {"security", "cyber", "engineering"},
    },
]


@dataclass(frozen=True)
class Persona:
    persona_id: str
    full_name: str
    email: str
    city: str
    graduation_year: int
    skills: list[str]
    interests: list[str]
    education: str
    queries: list[str]
    preferred_types: set[str]
    preferred_domains: set[str]


def _now() -> datetime:
    return datetime.utcnow()


def _sanitize(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "." for ch in value).strip(".")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _get_collection(document_cls: type) -> Any:
    getter = getattr(document_cls, "get_motor_collection", None)
    if callable(getter):
        return getter()
    getter = getattr(document_cls, "get_pymongo_collection", None)
    if callable(getter):
        return getter()
    raise AttributeError(f"No collection getter found for {document_cls.__name__}")


async def _init_db() -> AsyncIOMotorClient:
    client = AsyncIOMotorClient(settings.MONGODB_URL, tls=True, tlsAllowInvalidCertificates=True)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Profile,
            Opportunity,
            OpportunityInteraction,
            Application,
            OTPCode,
            Post,
            Comment,
            Experiment,
            ExperimentAssignment,
            RankingModelVersion,
            ModelDriftReport,
            NLPModelVersion,
            VectorIndexEntry,
        ],
    )
    return client


async def _ensure_experiment(key: str) -> Experiment:
    experiment = await Experiment.find_one(Experiment.key == key)
    if experiment:
        # Keep this simulation experiment deterministic and active.
        experiment.status = "active"
        variants = {variant.name for variant in experiment.variants}
        if "baseline" not in variants or "semantic" not in variants:
            experiment.variants = [
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="semantic", weight=1.0, is_control=False),
            ]
        experiment.updated_at = _now()
        await experiment.save()
        return experiment

    experiment = Experiment(
        key=key,
        description="Persona-based simulated traffic benchmark: baseline vs semantic ranking",
        status="active",
        variants=[
            ExperimentVariant(name="baseline", weight=1.0, is_control=True),
            ExperimentVariant(name="semantic", weight=1.0, is_control=False),
        ],
    )
    await experiment.insert()
    return experiment


def _build_personas(*, count: int, seed: int, email_prefix: str) -> list[Persona]:
    rng = random.Random(seed)
    personas: list[Persona] = []
    for index in range(max(1, count)):
        first_name = rng.choice(FIRST_NAMES)
        last_name = rng.choice(LAST_NAMES)
        template = rng.choice(PERSONA_TEMPLATES)
        city = rng.choice(INDIAN_CITIES)
        graduation_year = rng.choice([2024, 2025, 2026, 2027, 2028, 2029])
        persona_id = f"IN-PER-{index + 1:04d}"
        local_part = _sanitize(f"{email_prefix}.{first_name}.{last_name}.{index + 1:04d}")
        email = f"{local_part}@vidyaverse-sim.in"

        skills = list(dict.fromkeys(rng.sample(template["skills"], k=min(len(template["skills"]), rng.randint(4, 7)))))
        interests = list(
            dict.fromkeys(rng.sample(template["interests"], k=min(len(template["interests"]), rng.randint(2, 4))))
        )
        education = rng.choice(template["education"])

        personas.append(
            Persona(
                persona_id=persona_id,
                full_name=f"{first_name} {last_name}",
                email=email,
                city=city,
                graduation_year=graduation_year,
                skills=skills,
                interests=interests,
                education=education,
                queries=list(template["queries"]),
                preferred_types=set(template["preferred_types"]),
                preferred_domains=set(template["preferred_domains"]),
            )
        )
    return personas


async def _upsert_persona_user(persona: Persona, password_hash: str) -> tuple[User, Profile]:
    user = await User.find_one(User.email == persona.email)
    if not user:
        user = User(email=persona.email, hashed_password=password_hash, full_name=persona.full_name, is_active=True)
        await user.insert()

    profile = await Profile.find_one(Profile.user_id == user.id)
    profile_skills = ", ".join(persona.skills)
    profile_interests = ", ".join(persona.interests)
    bio = (
        f"{persona.full_name} is a final-year candidate from {persona.city} "
        f"graduating in {persona.graduation_year}, exploring {profile_interests.lower()}."
    )
    achievements = "Built academic projects, participated in hackathons, and actively applies to opportunities."

    if profile:
        profile.bio = bio
        profile.skills = profile_skills
        profile.interests = profile_interests
        profile.education = f"{persona.education} ({persona.graduation_year})"
        profile.achievements = achievements
        await profile.save()
    else:
        profile = Profile(
            user_id=user.id,
            bio=bio,
            skills=profile_skills,
            interests=profile_interests,
            education=f"{persona.education} ({persona.graduation_year})",
            achievements=achievements,
        )
        await profile.insert()

    return user, profile


def _title_domain_text(opportunity: Opportunity) -> str:
    return " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.domain or "",
            opportunity.opportunity_type or "",
            opportunity.university or "",
        ]
    ).lower()


def _compute_behavior_probabilities(
    *,
    persona: Persona,
    opportunity: Opportunity,
    rank_position: int,
    match_score: float,
    ranking_mode: str,
    rng: random.Random,
) -> dict[str, float]:
    text = _title_domain_text(opportunity)
    relevance = _clamp(match_score / 100.0, 0.0, 1.0)

    rank_decay = math.exp(-0.09 * max(0, rank_position - 1))
    domain_hit = any(token in text for token in persona.preferred_domains)
    type_hit = any(token in text for token in persona.preferred_types)
    city_hit = persona.city.lower() in text

    affinity_boost = 0.0
    if domain_hit:
        affinity_boost += 0.07
    if type_hit:
        affinity_boost += 0.06
    if city_hit:
        affinity_boost += 0.05

    # Realistic funnel: impression -> view -> click -> save/apply.
    view_prob = _clamp(0.10 + (0.65 * relevance * rank_decay) + affinity_boost, 0.03, 0.95)
    click_prob = _clamp(0.03 + (0.52 * relevance * rank_decay) + (0.7 * affinity_boost), 0.01, 0.85)
    save_given_click = _clamp(0.08 + (0.46 * relevance) + (0.4 * affinity_boost), 0.03, 0.80)
    apply_given_click = _clamp(0.02 + (0.24 * relevance) + (0.5 * affinity_boost), 0.01, 0.45)

    # Mild mode-quality bias keeps simulations plausible without overwhelming persona relevance.
    mode = (ranking_mode or "").lower().strip()
    mode_bias = {
        "baseline": 0.98,
        "semantic": 1.06,
        "ml": 1.10,
    }.get(mode, 1.0)

    # A small stochastic jitter keeps behavior non-uniform.
    jitter = 1.0 + rng.uniform(-0.10, 0.10)
    view_prob = _clamp(view_prob * jitter * mode_bias, 0.01, 0.95)
    click_prob = _clamp(click_prob * jitter * mode_bias, 0.005, 0.90)
    save_given_click = _clamp(save_given_click * jitter * mode_bias, 0.01, 0.85)
    apply_given_click = _clamp(apply_given_click * jitter * mode_bias, 0.005, 0.50)

    return {
        "view_prob": view_prob,
        "click_prob": click_prob,
        "save_given_click": save_given_click,
        "apply_given_click": apply_given_click,
    }


async def _clear_existing_simulation_data(*, experiment_key: str, email_prefix: str) -> None:
    safe_prefix = f"{_sanitize(email_prefix)}."
    users = [user for user in await User.find_many().to_list() if user.email.lower().startswith(safe_prefix)]
    user_ids = [user.id for user in users]
    if user_ids:
        await Profile.find_many(In(Profile.user_id, user_ids)).delete()
        await ExperimentAssignment.find_many(
            In(ExperimentAssignment.user_id, user_ids),
            ExperimentAssignment.experiment_key == experiment_key,
        ).delete()
        await OpportunityInteraction.find_many(In(OpportunityInteraction.user_id, user_ids)).delete()
        await User.find_many(In(User.id, user_ids)).delete()
    await OpportunityInteraction.find_many(OpportunityInteraction.experiment_key == experiment_key).delete()


async def _simulate(
    *,
    personas: list[Persona],
    experiment_key: str,
    impressions_per_persona: int,
    lookback_days: int,
    seed: int,
) -> dict[str, Any]:
    await _ensure_experiment(experiment_key)
    await experiment_service.ensure_defaults()

    opportunities = await Opportunity.find_many().sort("-last_seen_at").limit(1000).to_list()
    if not opportunities:
        raise RuntimeError("No opportunities found. Run scraper ingestion before simulation.")

    # A login-capable hash is unnecessary for offline simulation accounts.
    # Keep deterministic placeholder credentials to avoid local bcrypt backend issues.
    password_hash = "simulated_hash_v1"
    base_rng = random.Random(seed)
    interaction_docs: list[dict[str, Any]] = []

    session_duration_minutes = 90
    for idx, persona in enumerate(personas):
        persona_rng = random.Random(base_rng.randint(1, 10_000_000))
        user, profile = await _upsert_persona_user(persona, password_hash)
        decision = await experiment_service.assign(user_id=user.id, experiment_key=experiment_key)
        ranking_mode = decision.variant if decision else "semantic"
        query = persona_rng.choice(persona.queries)

        ranked, _meta = await recommendation_service.rank(
            user_id=user.id,
            profile=profile,
            opportunities=opportunities,
            limit=min(60, max(20, impressions_per_persona * 2)),
            ranking_mode=ranking_mode,
            query=query,
        )
        if not ranked:
            continue

        impressions_for_user = min(len(ranked), max(8, int(persona_rng.gauss(impressions_per_persona, 4))))
        session_start = _now() - timedelta(days=persona_rng.uniform(0.0, float(max(1, lookback_days))))

        for rank_pos, payload in enumerate(ranked[:impressions_for_user], start=1):
            opportunity: Opportunity = payload["opportunity"]
            match_score = float(payload.get("match_score") or 0.0)
            probs = _compute_behavior_probabilities(
                persona=persona,
                opportunity=opportunity,
                rank_position=rank_pos,
                match_score=match_score,
                ranking_mode=ranking_mode,
                rng=persona_rng,
            )

            impression_time = session_start + timedelta(
                minutes=min(
                    float(session_duration_minutes),
                    rank_pos * persona_rng.uniform(0.4, 2.5),
                )
            )

            common_payload = {
                "user_id": user.id,
                "opportunity_id": opportunity.id,
                "ranking_mode": ranking_mode,
                "experiment_key": experiment_key,
                "experiment_variant": ranking_mode,
                "traffic_type": "simulated",
                "query": query,
                "rank_position": rank_pos,
                "match_score": round(match_score, 4),
                "features": {
                    "simulation": True,
                    "simulation_type": "persona_based_india_v1",
                    "persona_id": persona.persona_id,
                    "city": persona.city,
                    "graduation_year": persona.graduation_year,
                    "baseline_score": payload.get("baseline_score"),
                    "semantic_score": payload.get("semantic_score"),
                    "behavior_score": payload.get("behavior_score"),
                },
            }

            interaction_docs.append(
                {
                    **common_payload,
                    "interaction_type": "impression",
                    "created_at": impression_time,
                }
            )

            viewed = persona_rng.random() < probs["view_prob"]
            clicked = persona_rng.random() < probs["click_prob"]
            saved = clicked and (persona_rng.random() < probs["save_given_click"])
            applied = clicked and (persona_rng.random() < probs["apply_given_click"])

            if viewed:
                interaction_docs.append(
                    {
                        **common_payload,
                        "interaction_type": "view",
                        "created_at": impression_time + timedelta(seconds=persona_rng.uniform(10, 120)),
                    }
                )
            if clicked:
                interaction_docs.append(
                    {
                        **common_payload,
                        "interaction_type": "click",
                        "created_at": impression_time + timedelta(seconds=persona_rng.uniform(15, 180)),
                    }
                )
            if saved:
                interaction_docs.append(
                    {
                        **common_payload,
                        "interaction_type": "save",
                        "created_at": impression_time + timedelta(seconds=persona_rng.uniform(60, 420)),
                    }
                )
            if applied:
                interaction_docs.append(
                    {
                        **common_payload,
                        "interaction_type": "apply",
                        "created_at": impression_time + timedelta(seconds=persona_rng.uniform(120, 720)),
                    }
                )

        if (idx + 1) % 50 == 0:
            print(f"[simulation] processed personas: {idx + 1}/{len(personas)}")

    if not interaction_docs:
        raise RuntimeError("Simulation generated zero interactions.")

    collection = _get_collection(OpportunityInteraction)
    await collection.insert_many(interaction_docs, ordered=False)

    interactions = await OpportunityInteraction.find_many(OpportunityInteraction.experiment_key == experiment_key).to_list()
    by_type: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    for item in interactions:
        by_type[item.interaction_type] = by_type.get(item.interaction_type, 0) + 1
        mode = item.ranking_mode or "unknown"
        by_mode[mode] = by_mode.get(mode, 0) + 1

    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        raise RuntimeError(f"Experiment {experiment_key} not found after simulation.")

    click_report = await experiment_analytics_service.report(
        experiment=experiment,
        days=max(1, lookback_days),
        conversion_types={"click"},
        traffic_type="simulated",
    )
    apply_report = await experiment_analytics_service.report(
        experiment=experiment,
        days=max(1, lookback_days),
        conversion_types={"apply"},
        traffic_type="simulated",
    )
    save_report = await experiment_analytics_service.report(
        experiment=experiment,
        days=max(1, lookback_days),
        conversion_types={"save"},
        traffic_type="simulated",
    )

    return {
        "simulation": {
            "experiment_key": experiment_key,
            "personas": len(personas),
            "interactions_inserted": len(interaction_docs),
            "lookback_days": lookback_days,
            "impressions_per_persona_target": impressions_per_persona,
            "breakdown_by_type": by_type,
            "breakdown_by_mode": by_mode,
        },
        "reports": {
            "click": click_report,
            "apply": apply_report,
            "save": save_report,
        },
    }


async def _build_real_pilot_snapshot(experiment_key: Optional[str], days: int) -> dict[str, Any]:
    if not experiment_key:
        return {"status": "skipped", "reason": "real_pilot_experiment_key_not_provided"}

    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        return {"status": "missing", "experiment_key": experiment_key}

    return {
        "status": "ok",
        "experiment_key": experiment_key,
        "click": await experiment_analytics_service.report(
            experiment=experiment,
            days=max(1, days),
            conversion_types={"click"},
            traffic_type="real",
        ),
        "apply": await experiment_analytics_service.report(
            experiment=experiment,
            days=max(1, days),
            conversion_types={"apply"},
            traffic_type="real",
        ),
        "save": await experiment_analytics_service.report(
            experiment=experiment,
            days=max(1, days),
            conversion_types={"save"},
            traffic_type="real",
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate realistic Indian persona-driven interaction traffic for A/B benchmarking."
    )
    parser.add_argument("--personas", type=int, default=300, help="Number of personas to generate (recommended 200-500).")
    parser.add_argument(
        "--impressions-per-persona",
        type=int,
        default=24,
        help="Target impressions per persona session (default 24).",
    )
    parser.add_argument("--lookback-days", type=int, default=14, help="Backfill horizon in days for timestamps.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument(
        "--experiment-key",
        type=str,
        default="ranking_mode_persona_sim",
        help="Experiment key used for simulated A/B traffic.",
    )
    parser.add_argument(
        "--real-pilot-experiment-key",
        type=str,
        default="ranking_mode",
        help="Existing live experiment key for real-pilot report snapshot.",
    )
    parser.add_argument(
        "--email-prefix",
        type=str,
        default="sim.india",
        help="Prefix used for generated simulated persona accounts.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete previous simulated accounts/interactions for this prefix and experiment key before generating.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="backend/benchmarks/simulated/persona_traffic_report.json",
        help="Path to write combined simulation + real pilot report JSON.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    client = await _init_db()
    try:
        if args.replace:
            await _clear_existing_simulation_data(experiment_key=str(args.experiment_key), email_prefix=str(args.email_prefix))

        personas = _build_personas(
            count=max(1, int(args.personas)),
            seed=int(args.seed),
            email_prefix=str(args.email_prefix),
        )
        simulation_payload = await _simulate(
            personas=personas,
            experiment_key=str(args.experiment_key),
            impressions_per_persona=max(6, int(args.impressions_per_persona)),
            lookback_days=max(1, int(args.lookback_days)),
            seed=int(args.seed),
        )

        real_pilot_payload = await _build_real_pilot_snapshot(
            experiment_key=str(args.real_pilot_experiment_key) if args.real_pilot_experiment_key else None,
            days=max(1, int(args.lookback_days)),
        )

        output = {
            "generated_at": _now().isoformat(),
            "transparency": {
                "label": "Simulated traffic benchmark (persona-based)",
                "note": "This dataset is synthetic and intended for load/performance and experimentation validation.",
            },
            "simulated_benchmark": simulation_payload,
            "real_pilot_snapshot": real_pilot_payload,
        }

        output_path = Path(args.out).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        print(json.dumps(output, indent=2, default=str))
        print(f"[simulation] report_written={output_path}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
