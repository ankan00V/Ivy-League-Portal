from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


TRUST_STATUS_VERIFIED = "verified"
TRUST_STATUS_UNREVIEWED = "unreviewed"
TRUST_STATUS_NEEDS_REVIEW = "needs_review"
TRUST_STATUS_BLOCKED = "blocked"

VISIBLE_TRUST_STATUSES = {TRUST_STATUS_VERIFIED, TRUST_STATUS_UNREVIEWED}
BLOCKING_RISK_SCORE = 75
REVIEW_RISK_SCORE = 45

PAYMENT_PATTERNS = [
    r"\b(application|registration|processing|security|training|interview|joining)\s+(fee|fees|charge|charges|deposit)\b",
    r"\bpay\s+(rs\.?|inr|₹|\$)?\s*\d+",
    r"\b(refundable|non[-\s]?refundable)\s+(deposit|fee)\b",
    r"\bwallet|upi|gpay|phonepe|paytm|bank\s+transfer\b",
]

IDENTITY_PATTERNS = [
    r"\bwhatsapp\s+(only|number|chat)\b",
    r"\btelegram\b",
    r"\bdm\s+for\s+(details|apply|registration)\b",
    r"\bno\s+interview\b",
]

UNREALISTIC_PATTERNS = [
    r"\bguaranteed\s+(job|internship|placement|selection)\b",
    r"\bearn\s+(rs\.?|inr|₹|\$)?\s*\d+.*\b(day|daily|week|weekly)\b",
    r"\bwork\s+.*\b\d+\s*(minutes|min)\b.*\bearn\b",
    r"\bno\s+(skills?|experience|resume)\s+required\b",
]

SHORTENER_HOSTS = {
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "cutt.ly",
    "shorturl.at",
    "rebrand.ly",
    "is.gd",
    "lnkd.in",
}

TRUSTED_HOST_KEYWORDS = {
    "edu",
    "ac.in",
    "gov.in",
    "aicte-india.org",
    "devfolio.co",
    "hackerearth.com",
    "devpost.com",
    "kaggle.com",
    "codeforces.com",
    "ycombinator.com",
    "wellfound.com",
    "linkedin.com",
}

SOURCE_HOST_ALLOWLISTS: dict[str, set[str]] = {
    "devfolio": {"devfolio.co"},
    "hackerearth": {"hackerearth.com"},
    "devpost": {"devpost.com"},
    "kaggle": {"kaggle.com"},
    "codeforces": {"codeforces.com"},
    "ycombinator_jobs": {"ycombinator.com"},
    "wellfound": {"wellfound.com"},
    "linkedin": {"linkedin.com"},
    "aicte_internship": {"aicte-india.org", "internship.aicte-india.org"},
    "handshake": {"joinhandshake.com", "handshake.com"},
}

HIGH_RISK_SOURCE_KEYWORDS = {
    "whatsapp",
    "telegram",
    "unknown",
    "manual",
}

SUSPICIOUS_TLDS = {".xyz", ".top", ".click", ".buzz", ".loan", ".work", ".gq", ".fit"}


@dataclass(frozen=True)
class OpportunityTrustAssessment:
    trust_status: str
    trust_score: int
    risk_score: int
    risk_reasons: list[str] = field(default_factory=list)
    verification_evidence: list[str] = field(default_factory=list)

    def as_update(self) -> dict[str, Any]:
        return {
            "trust_status": self.trust_status,
            "trust_score": self.trust_score,
            "risk_score": self.risk_score,
            "risk_reasons": list(self.risk_reasons),
            "verification_evidence": list(self.verification_evidence),
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _matches(patterns: list[str], haystack: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            matches.append(pattern)
    return matches


def _host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").strip().lower()


def _has_trusted_host(host: str) -> bool:
    if not host:
        return False
    return any(host == keyword or host.endswith(f".{keyword}") or keyword in host for keyword in TRUSTED_HOST_KEYWORDS)


def _matches_source_allowlist(source: str, host: str) -> bool:
    allowed_hosts = SOURCE_HOST_ALLOWLISTS.get(source, set())
    if not allowed_hosts:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def assess_opportunity_trust(payload: Any) -> OpportunityTrustAssessment:
    title = _text(getattr(payload, "title", None) if not isinstance(payload, dict) else payload.get("title"))
    description = _text(getattr(payload, "description", None) if not isinstance(payload, dict) else payload.get("description"))
    url = _text(getattr(payload, "url", None) if not isinstance(payload, dict) else payload.get("url"))
    source = _text(getattr(payload, "source", None) if not isinstance(payload, dict) else payload.get("source")).lower()
    university = _text(getattr(payload, "university", None) if not isinstance(payload, dict) else payload.get("university"))
    location = _text(getattr(payload, "location", None) if not isinstance(payload, dict) else payload.get("location"))
    eligibility = _text(getattr(payload, "eligibility", None) if not isinstance(payload, dict) else payload.get("eligibility"))

    haystack = " ".join([title, description, source, university, location, eligibility]).lower()
    host = _host(url)

    risk_score = 15
    reasons: list[str] = []
    evidence: list[str] = []

    payment_matches = _matches(PAYMENT_PATTERNS, haystack)
    if payment_matches:
        risk_score += 55
        reasons.append("Mentions fees, deposits, payment apps, or pay-to-apply language.")

    if _matches(IDENTITY_PATTERNS, haystack):
        risk_score += 25
        reasons.append("Uses off-platform contact channels or weak recruiter identity signals.")

    if _matches(UNREALISTIC_PATTERNS, haystack):
        risk_score += 25
        reasons.append("Uses unrealistic guarantee or easy-money language.")

    if not host:
        risk_score += 25
        reasons.append("Missing verifiable source URL.")
    elif host in SHORTENER_HOSTS:
        risk_score += 30
        reasons.append("Uses a shortened URL that hides the destination.")
    elif _matches_source_allowlist(source, host):
        risk_score -= 24
        evidence.append(f"Source label and host match an allowlisted platform: {source} -> {host}.")
    elif source in SOURCE_HOST_ALLOWLISTS:
        risk_score += 26
        reasons.append(f"Source label does not match its expected host allowlist: {source} -> {host}.")
    elif _has_trusted_host(host):
        risk_score -= 18
        evidence.append(f"Source host has a trusted institutional or established platform signal: {host}.")
    else:
        risk_score += 8
        reasons.append(f"Source host is not on the trusted allowlist: {host}.")

    if host and any(host.endswith(tld) for tld in SUSPICIOUS_TLDS):
        risk_score += 22
        reasons.append(f"Source host uses a suspicious top-level domain: {host}.")

    if url and not url.lower().startswith("https://"):
        risk_score += 8
        reasons.append("Source URL is not HTTPS.")

    if any(keyword in source for keyword in HIGH_RISK_SOURCE_KEYWORDS):
        risk_score += 15
        reasons.append("Source label is weak or manually supplied.")

    if len(description) < 80:
        risk_score += 12
        reasons.append("Description is too thin for a student-facing opportunity.")

    if university and university.lower() not in {"unknown", "n/a", "na"}:
        risk_score -= 5
        evidence.append(f"Organizer or institution supplied: {university}.")

    risk_score = max(0, min(100, risk_score))
    trust_score = 100 - risk_score

    if risk_score >= BLOCKING_RISK_SCORE:
        status = TRUST_STATUS_BLOCKED
    elif risk_score >= REVIEW_RISK_SCORE:
        status = TRUST_STATUS_NEEDS_REVIEW
    elif evidence:
        status = TRUST_STATUS_VERIFIED
    else:
        status = TRUST_STATUS_UNREVIEWED

    if not reasons and status == TRUST_STATUS_UNREVIEWED:
        reasons.append("No blocking risk found, but the source has not been manually verified.")

    return OpportunityTrustAssessment(
        trust_status=status,
        trust_score=trust_score,
        risk_score=risk_score,
        risk_reasons=reasons,
        verification_evidence=evidence,
    )


def apply_trust_assessment(target: Any, assessment: OpportunityTrustAssessment) -> None:
    for field_name, value in assessment.as_update().items():
        setattr(target, field_name, value)


def apply_trust_assessment_preserving_review(target: Any, assessment: OpportunityTrustAssessment) -> None:
    reviewed_by_user_id = getattr(target, "reviewed_by_user_id", None)
    reviewed_at = getattr(target, "reviewed_at", None)
    preserved_status = _text(getattr(target, "trust_status", TRUST_STATUS_UNREVIEWED)).lower() or TRUST_STATUS_UNREVIEWED
    preserved_evidence = list(getattr(target, "verification_evidence", []) or [])

    apply_trust_assessment(target, assessment)
    if reviewed_by_user_id is not None or reviewed_at is not None:
        target.trust_status = preserved_status
        if preserved_evidence:
            target.verification_evidence = preserved_evidence


def ensure_opportunity_trust(target: Any) -> OpportunityTrustAssessment:
    current_status = _text(getattr(target, "trust_status", TRUST_STATUS_UNREVIEWED)).lower() or TRUST_STATUS_UNREVIEWED
    current_trust_score = int(getattr(target, "trust_score", 50) or 50)
    current_risk_score = int(getattr(target, "risk_score", 50) or 50)
    current_risk_reasons = list(getattr(target, "risk_reasons", []) or [])
    current_verification_evidence = list(getattr(target, "verification_evidence", []) or [])

    if not (
        current_status == TRUST_STATUS_UNREVIEWED
        and current_trust_score == 50
        and current_risk_score == 50
        and not current_risk_reasons
        and not current_verification_evidence
    ):
        return OpportunityTrustAssessment(
            trust_status=current_status,
            trust_score=current_trust_score,
            risk_score=current_risk_score,
            risk_reasons=current_risk_reasons,
            verification_evidence=current_verification_evidence,
        )

    assessment = assess_opportunity_trust(target)
    apply_trust_assessment(target, assessment)
    return assessment


def is_trust_visible(opportunity: Any) -> bool:
    assessment = ensure_opportunity_trust(opportunity)
    status = assessment.trust_status
    risk_score = assessment.risk_score
    return status in VISIBLE_TRUST_STATUSES and risk_score < BLOCKING_RISK_SCORE
