from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from app.models.opportunity import Opportunity
from app.models.profile import Profile

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\n/]+", value) if item.strip()]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) >= 2}


def _opportunity_text(opportunity: Opportunity) -> str:
    return " ".join(
        [
            opportunity.title or "",
            opportunity.description or "",
            opportunity.domain or "",
            opportunity.opportunity_type or "",
            opportunity.university or "",
        ]
    ).strip()


def _deadline_days_left(deadline: datetime | None, *, now: datetime) -> float:
    if not deadline:
        return 9999.0
    value = deadline
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    delta = value - now_aware
    return float(delta.total_seconds() / 86400.0)


def _recency_hours(last_seen_at: datetime | None, *, now: datetime) -> float:
    if not last_seen_at:
        return 9999.0
    value = last_seen_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    delta = now_aware - value
    return float(max(0.0, delta.total_seconds() / 3600.0))


def _source_trust(opportunity: Opportunity) -> float:
    raw = (opportunity.source or "").strip().lower()
    if raw:
        mapping = {
            "unstop": 0.85,
            "internshala": 0.8,
            "naukri": 0.75,
            "indeed": 0.75,
            "hack2skill": 0.7,
            "freshersworld": 0.65,
        }
        for key, score in mapping.items():
            if key in raw:
                return float(score)

    try:
        host = (urlparse(opportunity.url or "").hostname or "").lower()
    except Exception:
        host = ""

    if host.endswith(".edu") or host.endswith(".ac.in"):
        return 0.9
    if any(token in host for token in ("linkedin.com", "github.com")):
        return 0.7
    if any(token in host for token in ("medium.com", "blogspot", "wordpress")):
        return 0.55
    return 0.6


@dataclass(frozen=True)
class RankerFeatures:
    values: dict[str, float]

    def as_ordered_vector(self, feature_names: list[str]) -> list[float]:
        return [float(self.values.get(name, 0.0)) for name in feature_names]


def build_ranker_features(
    *,
    profile: Profile,
    opportunity: Opportunity,
    semantic_score: float,
    skills_overlap_score: float,
    baseline_score: float,
    behavior_score: float,
    behavior_domain_pref: float,
    behavior_type_pref: float,
    now: datetime | None = None,
) -> RankerFeatures:
    """
    Feature set for learned ranking.

    Notes:
    - Scores are expected in [0, 100] for semantic/baseline/behavior.
    - Overlap scores are expected in [0, 1].
    - Preferences are expected in [0, 100] (normalized) for domain/type.
    """
    now = now or datetime.now(timezone.utc)

    opportunity_text = _opportunity_text(opportunity)
    opp_tokens = _tokens(opportunity_text)

    profile_skill_tokens = _tokens(" ".join(_split_csv(profile.skills)))
    profile_interest_tokens = _tokens(" ".join(_split_csv(profile.interests)))

    skill_overlap_count = float(len(profile_skill_tokens.intersection(opp_tokens)))
    interest_overlap_count = float(len(profile_interest_tokens.intersection(opp_tokens)))
    skill_token_count = float(len(profile_skill_tokens))
    interest_token_count = float(len(profile_interest_tokens))

    deadline_days = _deadline_days_left(opportunity.deadline, now=now)
    recency = _recency_hours(opportunity.last_seen_at, now=now)

    values: dict[str, float] = {
        # Core signals
        "semantic_score": float(semantic_score),
        "baseline_score": float(baseline_score),
        "behavior_score": float(behavior_score),
        "skills_overlap_score": float(skills_overlap_score),
        # Token overlaps (explicit)
        "skill_overlap_count": float(skill_overlap_count),
        "interest_overlap_count": float(interest_overlap_count),
        "skill_overlap_ratio": float(skill_overlap_count / max(1.0, skill_token_count)),
        "interest_overlap_ratio": float(interest_overlap_count / max(1.0, interest_token_count)),
        # Recency / deadline
        "recency_hours": float(min(recency, 9999.0)),
        "recency_log1p": float(math.log1p(min(recency, 9999.0))),
        "deadline_days_left": float(max(-9999.0, min(deadline_days, 9999.0))),
        "deadline_is_past": 1.0 if deadline_days < 0 else 0.0,
        "has_deadline": 1.0 if opportunity.deadline is not None else 0.0,
        # Source trust
        "source_trust": float(_source_trust(opportunity)),
        # Behavior preferences (normalized)
        "behavior_domain_pref": float(behavior_domain_pref),
        "behavior_type_pref": float(behavior_type_pref),
        "behavior_domain_pref_norm": float(behavior_domain_pref / 100.0),
        "behavior_type_pref_norm": float(behavior_type_pref / 100.0),
        # Text stats
        "opp_text_len": float(len(opportunity_text)),
        "opp_token_count": float(len(opp_tokens)),
    }
    return RankerFeatures(values=values)


def skills_overlap_score(*, profile: Profile, opportunity: Opportunity) -> float:
    opp_tokens = _tokens(_opportunity_text(opportunity))
    skill_tokens = _tokens(" ".join(_split_csv(profile.skills)))
    if not skill_tokens:
        return 0.0
    overlap = len(skill_tokens.intersection(opp_tokens))
    return float(overlap / max(1, len(skill_tokens)))

