import re
from datetime import datetime, timezone
from typing import Optional

from app.models.opportunity import Opportunity
from app.models.profile import Profile

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\n/]+", value) if item.strip()]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text) if len(token) >= 2}


def _profile_keywords(profile: Profile) -> set[str]:
    raw_parts = []
    raw_parts.extend(_split_csv(profile.skills))
    raw_parts.extend(_split_csv(profile.interests))
    raw_parts.extend(_split_csv(profile.education))
    raw_parts.extend(_split_csv(profile.achievements))
    return _tokens(" ".join(raw_parts))


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
    profile_kw = _profile_keywords(profile)
    if not profile_kw:
        return 0.0, ["Complete your profile skills/interests to unlock personalization."]

    reasons: list[str] = []
    score = 0.0

    opp_text = " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.domain or "",
            opportunity.opportunity_type or "",
            opportunity.university or "",
        ]
    )
    opp_kw = _tokens(opp_text)

    overlap = sorted(profile_kw.intersection(opp_kw))
    if overlap:
        overlap_points = min(50.0, len(overlap) * 6.0)
        score += overlap_points
        reasons.append(f"Keyword overlap: {', '.join(overlap[:4])}")

    domain_tokens = _tokens(opportunity.domain or "")
    interest_tokens = _tokens(" ".join(_split_csv(profile.interests)))
    skill_tokens = _tokens(" ".join(_split_csv(profile.skills)))

    if domain_tokens and interest_tokens and domain_tokens.intersection(interest_tokens):
        score += 20.0
        reasons.append("Domain aligns with your interests.")

    if domain_tokens and skill_tokens and domain_tokens.intersection(skill_tokens):
        score += 10.0
        reasons.append("Domain aligns with your listed skills.")

    if opportunity.deadline:
        deadline = opportunity.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        days_left = (deadline - datetime.now(timezone.utc)).days
        if days_left < 0:
            score -= 20.0
            reasons.append("Deadline has already passed.")
        elif days_left <= 14:
            score += 10.0
            reasons.append("Deadline is soon, high-priority opportunity.")

    return round(max(0.0, min(100.0, score)), 2), reasons
