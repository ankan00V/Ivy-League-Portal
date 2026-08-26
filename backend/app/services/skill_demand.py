"""What skills the live corpus is actually asking for, per domain.

The problem statement wants skill gaps measured "based on current industry
requirements". The cheap version of that is a hand-written list of skills, which
is really the author's guess about industry dated to the day they typed it. This
derives the same thing from the ~2,000 live postings already in the corpus, so
"in demand" means "appears in openings employers are advertising right now" and
moves on its own as the scrapers run.

Extraction runs over title + description rather than the stored `tags` column.
Tags carry provenance as well as skills - "official careers", "github-curated"
and company names like "tcs" are all in there - so demand built from tags would
confidently report that being github-curated is a sought-after skill.

The extractor is recall-oriented and returns sentence fragments alongside real
skills ("identify the customer s unique needs", "clinical care."), so everything
is normalised and filtered before it counts. A noisy skill list is worse than a
short one here: it is shown to students as advice.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# Soft skills are allowed to be longer than the word cap below, because the ones
# industry actually names are phrases ("attention to detail"). Everything else
# multi-word is far more likely to be a fragment of a sentence.
SOFT_SKILLS: frozenset[str] = frozenset(
    {
        "communication",
        "teamwork",
        "collaboration",
        "leadership",
        "problem solving",
        "critical thinking",
        "time management",
        "attention to detail",
        "adaptability",
        "creativity",
        "presentation",
        "negotiation",
        "public speaking",
        "interpersonal skills",
        "stakeholder management",
        "analytical thinking",
        "work ethic",
        "empathy",
        "customer service",
        "mentoring",
    }
)

# Fragments the extractor produces from prose. These lead sentences rather than
# naming a competency, so anything starting with one is discarded outright.
_FRAGMENT_LEADS = (
    "identify",
    "create",
    "ensure",
    "provide",
    "support the",
    "work with",
    "ability to",
    "responsible for",
    "assist",
    "perform",
    "maintain",
    "develop and",
    "help",
    "manage the",
)

# Sector and domain labels. The extractor surfaces these because postings name
# the industry they serve ("ML for health care", "retail analytics"), and they
# rank high enough to dominate a domain's table - the AI domain's top terms were
# health care, journalism, retail, hospitality and sports before this existed.
# They describe where the work happens, not what the student needs to be able to
# do, so as gap advice they are actively misleading.
_SECTOR_TERMS: frozenset[str] = frozenset(
    {
        "health care",
        "healthcare",
        "journalism",
        "retail",
        "hospitality",
        "sports",
        "education",
        "finance",
        "banking",
        "insurance",
        "manufacturing",
        "telecom",
        "logistics",
        "real estate",
        "agriculture",
        "government",
        "engineering",
        "science",
        "human resources",
        "marketing",
        "sales",
        "design",
        "law",
        "consulting",
        "media",
        "travel",
        "energy",
        "automotive",
        "gaming",
        "e commerce",
        "ecommerce",
        "technology",
        "business",
        "operations",
    }
)

# Pseudo-domain holding demand across every posting, used when a real domain
# is too thin to assess against.
GLOBAL_DOMAIN = "__all__"

# Below this a demand table cannot support a questionnaire worth answering.
MIN_USABLE_SKILLS = 6

_MAX_SKILL_WORDS = 3
_MAX_SKILL_CHARS = 40
_MIN_SKILL_CHARS = 2



def domain_key(domain: str) -> str:
    """Canonical form for matching a domain across sources.

    Profiles store the student's domain upper-cased ("AI AND MACHINE LEARNING")
    while opportunities store it title-cased ("AI and Machine Learning"). An
    exact match between the two never succeeds, so every student silently fell
    through to the whole-market table while the UI explained, confidently and
    wrongly, that their domain had too few postings. Matching on a canonical key
    is the only thing standing between this feature and looking like it works
    for everyone while working for no one.
    """
    return re.sub(r"\s+", " ", str(domain or "").strip()).casefold()


def normalise_skill(raw: str) -> Optional[str]:
    """Return a clean skill name, or None if this is not one.

    Rejecting is the important half. These strings are shown to a student as
    "you are missing this", so a fragment that survives becomes bad advice with
    an authoritative tone.
    """
    value = str(raw or "").strip().lower()
    # Extracted phrases keep the punctuation they were cut on ("clinical care.").
    value = value.strip(" .,;:!?-–—()[]{}\"'")
    value = re.sub(r"\s+", " ", value)
    # "customer s unique needs" - possessives lose their apostrophe upstream.
    value = re.sub(r"\bs\b", "", value).strip()
    value = re.sub(r"\s+", " ", value)

    if len(value) < _MIN_SKILL_CHARS or len(value) > _MAX_SKILL_CHARS:
        return None
    if value in SOFT_SKILLS:
        return value
    if value in _SECTOR_TERMS:
        return None
    if any(value.startswith(lead) for lead in _FRAGMENT_LEADS):
        return None
    if len(value.split()) > _MAX_SKILL_WORDS:
        return None
    # Pure numbers, or anything with no letters, is never a skill.
    if not re.search(r"[a-z]", value):
        return None
    return value


def is_soft_skill(skill: str) -> bool:
    return str(skill or "").strip().lower() in SOFT_SKILLS


@dataclass(frozen=True)
class SkillDemand:
    skill: str
    postings: int
    share: float
    is_soft: bool


def rank_demand(
    extracted_per_posting: Iterable[Iterable[str]],
    *,
    min_postings: int = 3,
    limit: int = 60,
) -> list[SkillDemand]:
    """Turn per-posting skill lists into a ranked demand table.

    `share` is the fraction of postings naming the skill, which is what makes
    demand comparable between a domain with 799 openings and one with 49.
    """
    counts: Counter[str] = Counter()
    total = 0
    for tags in extracted_per_posting:
        total += 1
        seen: set[str] = set()
        for tag in tags or []:
            skill = normalise_skill(tag)
            # Count each skill once per posting: a description repeating
            # "python" six times is one employer asking for python.
            if skill and skill not in seen:
                seen.add(skill)
        counts.update(seen)

    if not total:
        return []

    ranked = [
        SkillDemand(
            skill=skill,
            postings=n,
            share=round(n / total, 4),
            is_soft=is_soft_skill(skill),
        )
        for skill, n in counts.most_common()
        if n >= max(1, int(min_postings))
    ]
    return ranked[: max(1, int(limit))]


async def refresh_demand_snapshots(*, min_postings: int = 3, limit: int = 60) -> dict[str, Any]:
    """Recompute the per-domain demand tables from the live corpus.

    Runs as a background job rather than on request: extraction costs ~22ms per
    posting, so a full pass over the corpus is ~45 seconds. That is fine hourly
    and unacceptable inside a page load.

    Reads are paged for the same reason the vector rebuild is - a single
    statement over the whole table competes with the scrape batches for the GIL
    and gets starved past the job deadline.
    """
    from app.models.opportunity import Opportunity
    from app.models.skill_assessment import SkillDemandSnapshot
    from app.services.skill_extractor import skill_extractor

    page_size = 500
    per_domain: dict[str, list[list[str]]] = {}
    analysed = 0
    with_skills = 0
    loaded = 0

    while True:
        page = await Opportunity.find_many().sort("_id").skip(loaded).limit(page_size).to_list()
        if not page:
            break
        loaded += len(page)
        for opportunity in page:
            if str(getattr(opportunity, "opportunity_status", "") or "") != "active":
                continue
            domain = str(getattr(opportunity, "domain", None) or "Other").strip() or "Other"
            text = f"{opportunity.title or ''} {opportunity.description or ''}"
            tags = skill_extractor.extract(text, max_tags=12)
            per_domain.setdefault(domain, []).append(tags)
            analysed += 1
            if any(normalise_skill(tag) for tag in tags):
                with_skills += 1
        if len(page) < page_size:
            break
        logger.info("skill demand: scanned %s opportunities", loaded)

    # A global table as well as per-domain. Thin domains - Finance has 51 live
    # postings - cannot support a questionnaire on their own, and asking a
    # student five questions is worse than asking them fifteen from the wider
    # market.
    all_rows = [tags for rows in per_domain.values() for tags in rows]
    per_domain[GLOBAL_DOMAIN] = all_rows

    written = 0
    for domain, rows in per_domain.items():
        ranked = rank_demand(rows, min_postings=min_postings, limit=limit)
        if not ranked:
            continue
        await SkillDemandSnapshot(
            domain=domain,
            domain_key=domain_key(domain),
            skills=[
                {
                    "skill": item.skill,
                    "postings": item.postings,
                    "share": item.share,
                    "is_soft": item.is_soft,
                }
                for item in ranked
            ],
            postings_analysed=len(rows),
            postings_with_skills=sum(
                1 for tags in rows if any(normalise_skill(tag) for tag in tags)
            ),
        ).insert()
        written += 1

    result = {
        "status": "ok",
        "domains": written,
        "postings_analysed": analysed,
        "postings_with_skills": with_skills,
        "coverage": round(with_skills / analysed, 4) if analysed else 0.0,
    }
    logger.info("skill demand refresh: %s", result)
    return result


async def latest_snapshot(domain: str):
    """Newest demand table for a domain, falling back to the global one.

    The fallback matters: a domain with few live postings produces a table too
    short to assess anyone against, and silently returning three questions would
    look like the feature working.
    """
    from app.models.skill_assessment import SkillDemandSnapshot

    for candidate in (str(domain or "").strip(), GLOBAL_DOMAIN):
        if not candidate:
            continue
        rows = (
            await SkillDemandSnapshot.find_many(
                SkillDemandSnapshot.domain_key == domain_key(candidate)
            )
            .sort("-created_at")
            .limit(1)
            .to_list()
        )
        if rows and len(rows[0].skills) >= MIN_USABLE_SKILLS:
            return rows[0]
    return None
