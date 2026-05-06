import re
from datetime import datetime, timezone
from typing import Optional

from app.models.opportunity import Opportunity
from app.models.profile import Profile

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
EVERGREEN_SIGNALS = {
    "Google Summer of Code": {"google summer of code", "summer of code", "gsoc"},
    "GirlScript Summer of Code": {"girlscript summer of code", "gssoc"},
    "Outreachy": {"outreachy"},
    "MLH Fellowship": {"mlh fellowship"},
    "Google Season of Docs": {"season of docs"},
    "Hacktoberfest": {"hacktoberfest"},
    "Open Source": {"open source", "opensource"},
}
DISCOVERY_SIGNALS = {
    "internship",
    "intern",
    "hackathon",
    "challenge",
    "competition",
    "fellowship",
    "program",
    "student",
    "open source",
    "opensource",
}


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\n/]+", value) if item.strip()]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) >= 2}


def _core_profile_keywords(profile: Profile) -> set[str]:
    raw_parts = []
    raw_parts.extend(_split_csv(profile.skills))
    raw_parts.extend(_split_csv(profile.interests))
    raw_parts.extend(_split_csv(profile.education))
    raw_parts.extend(_split_csv(profile.achievements))
    return _tokens(" ".join(raw_parts))


def _seed_profile_keywords(profile: Profile) -> set[str]:
    raw_parts = []
    raw_parts.extend(
        [
            getattr(profile, "bio", "") or "",
            getattr(profile, "domain", "") or "",
            getattr(profile, "course", "") or "",
            getattr(profile, "course_specialization", "") or "",
            getattr(profile, "current_job_role", "") or "",
            getattr(profile, "experience_summary", "") or "",
            getattr(profile, "preferred_roles", "") or "",
            getattr(profile, "preferred_locations", "") or "",
        ]
    )
    raw_parts.extend(getattr(profile, "goals", []) or [])
    return _tokens(" ".join(raw_parts))


def _profile_keywords(profile: Profile) -> set[str]:
    primary = _core_profile_keywords(profile)
    return primary or _seed_profile_keywords(profile)


def _opportunity_text(opportunity: Opportunity) -> str:
    return " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.domain or "",
            opportunity.opportunity_type or "",
            opportunity.university or "",
        ]
    )


def _evergreen_labels(opportunity: Opportunity) -> list[str]:
    haystack = _opportunity_text(opportunity).lower()
    labels: list[str] = []
    for label, keywords in EVERGREEN_SIGNALS.items():
        if any(keyword in haystack for keyword in keywords):
            labels.append(label)
    return labels


def _deadline_score(opportunity: Opportunity) -> tuple[float, list[str]]:
    if not opportunity.deadline:
        return 0.0, []

    deadline = opportunity.deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    days_left = (deadline - datetime.now(timezone.utc)).days
    if days_left < 0:
        return -20.0, ["Deadline has already passed."]
    if days_left <= 14:
        return 10.0, ["Deadline is soon, high-priority opportunity."]
    if days_left <= 45:
        return 4.0, ["Deadline is active, worth reviewing now."]
    return 0.0, []


def _generic_discovery_score(opportunity: Opportunity) -> tuple[float, list[str]]:
    score = 8.0
    reasons: list[str] = ["Showing live opportunities while your profile personalizes."]
    haystack = _opportunity_text(opportunity).lower()

    evergreen = _evergreen_labels(opportunity)
    if evergreen:
        score += 30.0
        reasons.append(f"Evergreen program detected: {', '.join(evergreen[:2])}")

    if any(keyword in haystack for keyword in DISCOVERY_SIGNALS):
        score += 10.0
        reasons.append("High-discovery opportunity for students and early-career candidates.")

    deadline_score, deadline_reasons = _deadline_score(opportunity)
    score += deadline_score
    reasons.extend(deadline_reasons)
    return round(max(0.0, min(100.0, score)), 2), reasons


def calculate_incoscore(profile: Profile) -> float:
    skills = list({item.lower() for item in _split_csv(profile.skills)})
    interests = list({item.lower() for item in _split_csv(profile.interests)})
    achievements = _split_csv(profile.achievements)

    base_score = 10.0
    skill_score = min(35.0, len(skills) * 4.0)
    interest_score = min(15.0, len(interests) * 3.0)
    achievement_score = min(20.0, len(achievements) * 5.0)
    education_score = 10.0 if (profile.education and profile.education.strip()) else 0.0
    resume_score = 10.0 if (profile.resume_url and profile.resume_url.strip()) else 0.0

    total = base_score + skill_score + interest_score + achievement_score + education_score + resume_score
    return round(min(100.0, total), 2)


def score_opportunity_match(profile: Profile, opportunity: Opportunity) -> tuple[float, list[str]]:
    core_profile_kw = _core_profile_keywords(profile)
    profile_kw = core_profile_kw or _seed_profile_keywords(profile)
    cold_start_mode = not core_profile_kw and bool(profile_kw)
    if not profile_kw:
        return _generic_discovery_score(opportunity)

    reasons: list[str] = []
    score = 0.0

    opp_text = _opportunity_text(opportunity)
    opp_kw = _tokens(opp_text)

    overlap = sorted(profile_kw.intersection(opp_kw))
    if overlap:
        overlap_points = min(50.0, len(overlap) * 6.0)
        score += overlap_points
        reasons.append(f"Keyword overlap: {', '.join(overlap[:4])}")
        if cold_start_mode:
            reasons.append("Matched from your onboarding profile signals.")

    domain_tokens = _tokens(opportunity.domain or "")
    interest_tokens = _tokens(" ".join(_split_csv(profile.interests)))
    skill_tokens = _tokens(" ".join(_split_csv(profile.skills)))
    seed_tokens = _seed_profile_keywords(profile)

    if domain_tokens and interest_tokens and domain_tokens.intersection(interest_tokens):
        score += 20.0
        reasons.append("Domain aligns with your interests.")

    if domain_tokens and skill_tokens and domain_tokens.intersection(skill_tokens):
        score += 10.0
        reasons.append("Domain aligns with your listed skills.")

    if cold_start_mode and domain_tokens and seed_tokens and domain_tokens.intersection(seed_tokens):
        score += 12.0
        reasons.append("Domain aligns with your onboarding preferences.")

    evergreen = _evergreen_labels(opportunity)
    if evergreen:
        score += 18.0
        reasons.append(f"Evergreen opportunity: {', '.join(evergreen[:2])}")

    deadline_score, deadline_reasons = _deadline_score(opportunity)
    score += deadline_score
    reasons.extend(deadline_reasons)

    return round(max(0.0, min(100.0, score)), 2), reasons
