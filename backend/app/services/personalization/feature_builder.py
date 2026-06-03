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
HEURISTIC_WEIGHT_FEATURES = ["semantic_score", "baseline_score", "behavior_score"]

DEFAULT_LEARNED_RANKER_FEATURES = [
    "semantic_score",
    "baseline_score",
    "behavior_score",
    "skills_overlap_score",
    "skill_overlap_count",
    "interest_overlap_count",
    "intent_overlap_count",
    "work_pref_overlap_count",
    "skill_overlap_ratio",
    "interest_overlap_ratio",
    "intent_overlap_ratio",
    "work_pref_overlap_ratio",
    "recency_hours",
    "recency_log1p",
    "deadline_days_left",
    "deadline_is_past",
    "has_deadline",
    "deadline_urgency_score",
    "freshness_decay_24h",
    "source_trust",
    "source_trust_bucket",
    "source_diversity_bonus",
    "opportunity_quality_score",
    "opportunity_quality_norm",
    "opportunity_quality_low",
    "opportunity_freshness_14d",
    "opportunity_source_count_log1p",
    "opportunity_dedup_score",
    "stipend_fit_score",
    "pref_work_mode",
    "pref_location",
    "profile_completeness",
    "days_since_onboarding_norm",
    "interaction_count_log1p",
    "behavior_domain_pref",
    "behavior_type_pref",
    "behavior_source_pref",
    "behavior_domain_pref_norm",
    "behavior_type_pref_norm",
    "behavior_source_pref_norm",
    "user_recent_interactions_7d",
    "user_recent_interactions_30d",
    "user_recent_applies_30d",
    "user_recent_clicks_30d",
    "user_recent_impressions_30d",
    "user_last_interaction_hours",
    "user_last_interaction_log1p",
    "sequence_ctr_30d",
    "user_ctr_30d",
    "ctr_for_source",
    "ctr_for_domain",
    "days_since_last_interaction_norm",
    "geo_match_score",
    "has_geo_preference",
    "opp_text_len",
    "opp_token_count",
]
RANKER_FEATURE_SCHEMA_VERSION = "ranker-features-v3"


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;\n/]+", value) if item.strip()]


def _split_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return _split_csv(value)
    return []


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


def _location_tokens(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    tokens = _tokens(value)
    return {token for token in tokens if len(token) >= 3}


def _profile_location_tokens(profile: Profile) -> set[str]:
    candidates = [
        str(getattr(profile, "preferred_locations", "") or ""),
        str(getattr(profile, "current_address_region", "") or ""),
        str(getattr(profile, "permanent_address_region", "") or ""),
        str(getattr(profile, "college_name", "") or ""),
    ]
    merged: set[str] = set()
    for item in candidates:
        merged.update(_location_tokens(item))
    return merged


def _opportunity_location_tokens(opportunity: Opportunity) -> set[str]:
    candidates = [
        str(getattr(opportunity, "location", "") or ""),
        str(getattr(opportunity, "university", "") or ""),
        str(getattr(opportunity, "title", "") or ""),
        str(getattr(opportunity, "description", "") or ""),
    ]
    merged: set[str] = set()
    for item in candidates:
        merged.update(_location_tokens(item))
    return merged


def _geo_match_score(profile: Profile, opportunity: Opportunity) -> float:
    profile_tokens = _profile_location_tokens(profile)
    if not profile_tokens:
        if bool(getattr(profile, "pan_india", False) or getattr(profile, "prefer_wfh", False)):
            return 1.0
        return 0.0
    opportunity_tokens = _opportunity_location_tokens(opportunity)
    if not opportunity_tokens:
        return 0.0
    overlap = len(profile_tokens.intersection(opportunity_tokens))
    return float(overlap / max(1, len(profile_tokens)))


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
    raw = (str(getattr(opportunity, "source", "") or "")).strip().lower()
    if raw:
        mapping = {
            "unstop": 0.85,
            "internshala": 0.8,
            "naukri": 0.75,
            "indeed": 0.75,
            "linkedin": 0.86,
            "major_league_hacking": 0.84,
            "mlh": 0.84,
            "glassdoor": 0.78,
            "foundit": 0.76,
            "devfolio": 0.82,
            "hackerearth": 0.8,
            "devpost": 0.8,
            "techgig": 0.74,
            "reskilll": 0.7,
            "instahyre": 0.81,
            "hirist": 0.79,
            "cuvette": 0.76,
            "aicte": 0.84,
            "smartinternz": 0.74,
            "makeintern": 0.68,
            "letsintern": 0.67,
            "handshake": 0.78,
            "wellfound": 0.82,
            "ycombinator_jobs": 0.88,
            "wayup": 0.74,
            "chegg": 0.72,
            "kaggle": 0.83,
            "codeforces": 0.8,
            "geeksforgeeks": 0.75,
            "promilo": 0.65,
            "hack2skill": 0.7,
            "freshersworld": 0.65,
        }
        for key, score in mapping.items():
            if key in raw:
                return float(score)

    try:
        host = (urlparse(str(getattr(opportunity, "url", "") or "")).hostname or "").lower()
    except Exception:
        host = ""

    if host.endswith(".edu") or host.endswith(".ac.in"):
        return 0.9
    if any(token in host for token in ("linkedin.com", "github.com")):
        return 0.7
    if any(token in host for token in ("medium.com", "blogspot", "wordpress")):
        return 0.55
    return 0.6


def _profile_completeness(profile: Profile) -> float:
    fields = [
        getattr(profile, "domain", None),
        getattr(profile, "course", None),
        getattr(profile, "preferred_roles", None),
        getattr(profile, "preferred_locations", None),
        getattr(profile, "skills", None),
        getattr(profile, "interests", None),
        getattr(profile, "bio", None),
        getattr(profile, "passout_year", None),
        getattr(profile, "work_preferences", None),
        getattr(profile, "career_intent", None),
    ]
    complete = 0
    for value in fields:
        if isinstance(value, list):
            complete += 1 if value else 0
        elif value:
            complete += 1
    return float(complete / max(1, len(fields)))


def _days_since(value: datetime | None, *, now: datetime) -> float:
    if value is None:
        return 9999.0
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return float(max(0.0, (now_aware - current).total_seconds() / 86400.0))


def _work_mode_match(profile: Profile, opportunity: Opportunity) -> float:
    opp_work_mode = str(getattr(opportunity, "work_mode", "") or "").strip().lower()
    if not opp_work_mode:
        return 0.0
    profile_tokens = _tokens(" ".join(_split_list(getattr(profile, "work_preferences", []))))
    if bool(getattr(profile, "prefer_wfh", False)):
        profile_tokens.add("remote")
    if not profile_tokens:
        return 0.0
    if opp_work_mode in profile_tokens:
        return 1.0
    if opp_work_mode == "remote" and {"wfh", "work", "home"}.intersection(profile_tokens):
        return 1.0
    return 0.0


def _stipend_fit_score(profile: Profile, opportunity: Opportunity) -> float:
    stipend_min = float(getattr(opportunity, "stipend_min", None) or 0.0)
    stipend_max = float(getattr(opportunity, "stipend_max", None) or stipend_min or 0.0)
    if stipend_min <= 0 and stipend_max <= 0:
        return 0.0
    profile_text = " ".join(
        [
            str(getattr(profile, "preferred_roles", "") or ""),
            str(getattr(profile, "goals", "") or ""),
            str(getattr(profile, "career_intent", "") or ""),
        ]
    ).lower()
    if "unpaid" in profile_text or "research" in profile_text:
        return 0.5
    if stipend_max >= 20_000:
        return 1.0
    if stipend_max >= 10_000:
        return 0.75
    return 0.5


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
    behavior_source_pref: float = 0.0,
    user_recent_interactions_7d: float = 0.0,
    user_recent_interactions_30d: float = 0.0,
    user_recent_applies_30d: float = 0.0,
    user_recent_clicks_30d: float = 0.0,
    user_recent_impressions_30d: float = 0.0,
    user_last_interaction_hours: float = 9999.0,
    sequence_ctr_30d: float = 0.0,
    source_diversity_bonus: float = 0.0,
    ctr_for_source: float = 0.0,
    ctr_for_domain: float = 0.0,
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
    profile_interest_tokens = _tokens(
        " ".join(_split_csv(profile.interests) + _split_list(getattr(profile, "interest_graph", [])))
    )
    profile_intent_tokens = _tokens(" ".join(_split_list(getattr(profile, "career_intent", []))))
    profile_work_pref_tokens = _tokens(" ".join(_split_list(getattr(profile, "work_preferences", []))))

    skill_overlap_count = float(len(profile_skill_tokens.intersection(opp_tokens)))
    interest_overlap_count = float(len(profile_interest_tokens.intersection(opp_tokens)))
    intent_overlap_count = float(len(profile_intent_tokens.intersection(opp_tokens)))
    work_pref_overlap_count = float(len(profile_work_pref_tokens.intersection(opp_tokens)))
    skill_token_count = float(len(profile_skill_tokens))
    interest_token_count = float(len(profile_interest_tokens))

    deadline_days = _deadline_days_left(opportunity.deadline, now=now)
    recency = _recency_hours(opportunity.last_seen_at, now=now)
    geo_match = _geo_match_score(profile, opportunity)
    source_trust = _source_trust(opportunity)
    raw_quality_score = getattr(opportunity, "quality_score", None)
    quality_score = 50.0 if raw_quality_score is None else float(raw_quality_score)
    quality_score = max(0.0, min(100.0, quality_score))
    profile_completeness = _profile_completeness(profile)
    onboarding_days = _days_since(getattr(profile, "onboarding_completed_at", None), now=now)
    pref_work_mode = _work_mode_match(profile, opportunity)
    pref_location = _geo_match_score(profile, opportunity)
    freshness_days = _days_since(getattr(opportunity, "last_seen_at", None), now=now)
    dedup_score = float(getattr(opportunity, "dedup_score", 0.0) or 0.0)
    source_count = float(getattr(opportunity, "source_count", 1.0) or 1.0)
    stipend_fit = _stipend_fit_score(profile, opportunity)
    user_recent_impressions_safe = max(0.0, float(user_recent_impressions_30d))
    user_recent_clicks_safe = max(0.0, float(user_recent_clicks_30d))
    user_ctr = float(user_recent_clicks_safe / max(1.0, user_recent_impressions_safe))

    values: dict[str, float] = {
        # Core signals
        "semantic_score": float(semantic_score),
        "baseline_score": float(baseline_score),
        "behavior_score": float(behavior_score),
        "skills_overlap_score": float(skills_overlap_score),
        # Token overlaps (explicit)
        "skill_overlap_count": float(skill_overlap_count),
        "interest_overlap_count": float(interest_overlap_count),
        "intent_overlap_count": float(intent_overlap_count),
        "work_pref_overlap_count": float(work_pref_overlap_count),
        "skill_overlap_ratio": float(skill_overlap_count / max(1.0, skill_token_count)),
        "interest_overlap_ratio": float(interest_overlap_count / max(1.0, interest_token_count)),
        "intent_overlap_ratio": float(intent_overlap_count / max(1.0, float(len(profile_intent_tokens)))),
        "work_pref_overlap_ratio": float(work_pref_overlap_count / max(1.0, float(len(profile_work_pref_tokens)))),
        # Recency / deadline
        "recency_hours": float(min(recency, 9999.0)),
        "recency_log1p": float(math.log1p(min(recency, 9999.0))),
        "deadline_days_left": float(max(-9999.0, min(deadline_days, 9999.0))),
        "deadline_is_past": 1.0 if deadline_days < 0 else 0.0,
        "has_deadline": 1.0 if opportunity.deadline is not None else 0.0,
        "deadline_urgency_score": float(1.0 / (1.0 + max(0.0, deadline_days))),
        "freshness_decay_24h": float(math.exp(-min(recency, 2400.0) / 24.0)),
        # Source trust
        "source_trust": float(source_trust),
        "source_trust_bucket": float(2.0 if source_trust >= 0.82 else 1.0 if source_trust >= 0.7 else 0.0),
        "source_diversity_bonus": float(max(0.0, min(1.0, source_diversity_bonus))),
        "opportunity_quality_score": float(quality_score),
        "opportunity_quality_norm": float(quality_score / 100.0),
        "opportunity_quality_low": 1.0 if quality_score < 30.0 else 0.0,
        "opportunity_freshness_14d": float(math.exp(-min(freshness_days, 365.0) / 14.0)),
        "opportunity_source_count_log1p": float(math.log1p(max(0.0, source_count))),
        "opportunity_dedup_score": float(max(0.0, min(1.0, dedup_score))),
        "stipend_fit_score": float(max(0.0, min(1.0, stipend_fit))),
        "pref_work_mode": float(pref_work_mode),
        "pref_location": float(max(0.0, min(1.0, pref_location))),
        "profile_completeness": float(profile_completeness),
        "days_since_onboarding_norm": float(min(onboarding_days, 90.0) / 90.0),
        "interaction_count_log1p": float(math.log1p(max(0.0, user_recent_interactions_30d))),
        # Behavior preferences (normalized)
        "behavior_domain_pref": float(behavior_domain_pref),
        "behavior_type_pref": float(behavior_type_pref),
        "behavior_source_pref": float(behavior_source_pref),
        "behavior_domain_pref_norm": float(behavior_domain_pref / 100.0),
        "behavior_type_pref_norm": float(behavior_type_pref / 100.0),
        "behavior_source_pref_norm": float(behavior_source_pref / 100.0),
        # User sequence dynamics
        "user_recent_interactions_7d": float(max(0.0, user_recent_interactions_7d)),
        "user_recent_interactions_30d": float(max(0.0, user_recent_interactions_30d)),
        "user_recent_applies_30d": float(max(0.0, user_recent_applies_30d)),
        "user_recent_clicks_30d": float(user_recent_clicks_safe),
        "user_recent_impressions_30d": float(user_recent_impressions_safe),
        "user_last_interaction_hours": float(max(0.0, user_last_interaction_hours)),
        "user_last_interaction_log1p": float(math.log1p(max(0.0, user_last_interaction_hours))),
        "sequence_ctr_30d": float(max(0.0, min(1.0, sequence_ctr_30d))),
        "user_ctr_30d": float(max(0.0, min(1.0, user_ctr))),
        "ctr_for_source": float(max(0.0, min(1.0, ctr_for_source))),
        "ctr_for_domain": float(max(0.0, min(1.0, ctr_for_domain))),
        "days_since_last_interaction_norm": float(min(max(0.0, user_last_interaction_hours) / 24.0, 30.0) / 30.0),
        # Geo fit
        "geo_match_score": float(max(0.0, min(1.0, geo_match))),
        "has_geo_preference": 1.0 if _profile_location_tokens(profile) else 0.0,
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
