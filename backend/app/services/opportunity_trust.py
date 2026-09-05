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
    # These target the *candidate* being asked to pay. The previous form,
    # `pay\s+(currency)?\s*\d+`, also matched legitimate compensation such as
    # "We pay 25000 per month stipend" and flagged the posting for review.
    r"(?<!\bwe\s)\bpay\s+(?:rs\.?|inr|₹|\$)\s*\d+",
    r"\bpay\s+(?:rs\.?|inr|₹|\$)?\s*\d+[^.]{0,40}\b(?:fee|fees|deposit|to\s+(?:apply|join|register|start))\b",
    r"\b(refundable|non[-\s]?refundable)\s+(deposit|fee)\b",
]

# Naming a payment rail is not evidence of anything on its own.
#
# These were inside PAYMENT_PATTERNS, so any posting containing the word "Paytm"
# or "UPI" scored +55 and was held for review. Measured against 400 live
# listings the detector scored precision 0.17: it was hiding real internships at
# Paytm, PhonePe, Cashfree and Razorpay - companies whose job descriptions
# necessarily talk about wallets and UPI - while the corpus contained no genuine
# pay-to-apply fraud at all.
#
# The distinction that matters is who is being asked to pay. "Paytm is India's
# leading payments company" describes an employer. "Send Rs 750 to this UPI to
# confirm your seat" is a demand on the reader. A rail name only counts as a
# signal when it appears alongside such a demand, which is what
# _mentions_payment_demand checks.
PAYMENT_RAIL_PATTERNS = [
    r"\b(?:wallet|upi|gpay|phonepe|paytm|bank\s+transfer)\b",
]

#: Words that turn a rail mention into a demand: money moving away from the
#: reader. Scoped tightly - "receive" and "salary" are deliberately absent.
_RAIL_DEMAND_CONTEXT = re.compile(
    r"\b(send|transfer|deposit|pay|payment\s+of|remit|share\s+screenshot)\b",
    re.IGNORECASE,
)
#: How close the demand verb has to sit to the rail name. A description can
#: mention UPI in paragraph one and a stipend in paragraph nine without the two
#: having anything to do with each other.
_RAIL_PROXIMITY_CHARS = 80

#: What separates an instruction to pay from prose about payments.
#:
#: Requiring a money *amount* alone was too strict, and the existing scraper
#: tests caught it: "Send money to our paytm wallet" and "transfer via upi to
#: confirm your seat" are both fraud and neither names a figure. My evaluation
#: set had missed that because every synthetic example I wrote happened to quote
#: a sum, so it scored a perfect recall it had not earned.
#:
#: Any one of three is enough:
#:   - a sum          "Send Rs 750 to this UPI"
#:   - a money noun   "Send money to our paytm wallet"
#:   - a reader-directed purpose  "transfer via upi to confirm your seat"
#:
#: "Analyse bank transfer success rates and UPI failure modes" has none of them,
#: which is why it stays clear.
_DEMAND_EVIDENCE = re.compile(
    r"(?:rs\.?|inr|₹|\$)\s*\d"
    r"|\d{2,}\s*(?:rs\.?|inr|₹|/-)"
    r"|\b(?:money|fee|fees|deposit|charges?|amount)\b"
    r"|\bto\s+(?:confirm|secure|reserve|activate|unlock|join|apply|register|start)\b",
    re.IGNORECASE,
)

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
    # Applicant tracking systems. A posting served from Lever or Greenhouse was
    # scoring +8 as "not on the trusted allowlist" while being exactly the kind
    # of host a real employer uses - these carry the four Paytm internships that
    # the payment-rail bug was hiding.
    "jobs.lever.co",
    "greenhouse.io",
    "ashbyhq.com",
    "smartrecruiters.com",
    "myworkdayjobs.com",
    "edu",
    "ac.in",
    "gov.in",
    "aicte-india.org",
    "unstop.com",
    "internshala.com",
    "devfolio.co",
    "hackerearth.com",
    "devpost.com",
    "reskilll.com",
    "hack2skill.com",
    "mlh.io",
    "kaggle.com",
    "codeforces.com",
    "ycombinator.com",
    "wellfound.com",
    "linkedin.com",
    "naukri.com",
    "indeed.com",
    "instahyre.com",
    "hirist.tech",
    "cuvette.tech",
    "greenhouse.io",
    "remotive.com",
    "remoteok.com",
    "weworkremotely.com",
    "remotees.com",
    "remotehabits.com",
    "nodesk.co",
    "remote4me.com",
    "justremote.co",
    "workingnomads.com",
    "jobspresso.co",
    "virtualvocations.com",
    "freelancer.com",
    "simplyhired.com",
    "monster.com",
    "careerbuilder.com",
    "zintellect.com",
    "interstride.com",
    "untapped.io",
    "parkerdewey.com",
    "extern.com",
    "github.com",
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
    "unstop": {"unstop.com"},
    "internshala": {"internshala.com"},
    "reskilll": {"reskilll.com"},
    "hack2skill": {"hack2skill.com"},
    "major_league_hacking": {"mlh.io"},
    "naukri": {"naukri.com"},
    "indeed": {"indeed.com", "in.indeed.com"},
    "instahyre": {"instahyre.com"},
    "hirist": {"hirist.tech"},
    "cuvette": {"cuvette.tech"},
    "aicte_internship": {"aicte-india.org", "internship.aicte-india.org"},
    "handshake": {"joinhandshake.com", "handshake.com"},
    "greenhouse": {"greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"},
    "remotive": {"remotive.com"},
    "remoteok": {"remoteok.com"},
    "remoteok_asia": {"remoteok.com"},
    "remoteok_europe": {"remoteok.com"},
    "we_work_remotely": {"weworkremotely.com"},
    "remotees": {"remotees.com"},
    "remote_habits": {"remotehabits.com"},
    "nodesk": {"nodesk.co"},
    "remote4me": {"remote4me.com"},
    "justremote": {"justremote.co"},
    "working_nomads": {"workingnomads.com"},
    "jobspresso": {"jobspresso.co"},
    "virtual_vocations": {"virtualvocations.com"},
    "freelancer": {"freelancer.com"},
    "simplyhired": {"simplyhired.com"},
    "monster": {"monster.com"},
    "careerbuilder": {"careerbuilder.com"},
    "zintellect": {"zintellect.com"},
    "interstride": {"interstride.com"},
    "untapped": {"untapped.io"},
    "parker_dewey": {"parkerdewey.com"},
    "extern": {"extern.com"},
    "github_internship_lists": {"github.com"},
    "linkedin_remote": {"linkedin.com"},
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


def _mentions_payment_demand(haystack: str) -> bool:
    """True when a payment rail is named in the context of money leaving the reader.

    Checked by proximity rather than mere co-occurrence: a fintech job
    description mentions UPI in its company blurb and a stipend several
    paragraphs later, and treating that as a demand is what produced 29 false
    positives against zero real fraud.
    """
    for pattern in PAYMENT_RAIL_PATTERNS:
        for match in re.finditer(pattern, haystack, re.IGNORECASE):
            # The window excludes the match itself. "bank transfer" contains its
            # own demand verb, so a listing analysing "bank transfer success
            # rates" was reading as a demand to transfer money.
            before = haystack[max(0, match.start() - _RAIL_PROXIMITY_CHARS):match.start()]
            after = haystack[match.end():match.end() + _RAIL_PROXIMITY_CHARS]
            window = before + after
            if _RAIL_DEMAND_CONTEXT.search(window) and _DEMAND_EVIDENCE.search(window):
                return True
    return False


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

    # An explicit demand - a fee, a deposit, pay-to-apply - is strong on its own.
    if _matches(PAYMENT_PATTERNS, haystack):
        risk_score += 55
        reasons.append("Asks the candidate for a fee, deposit or payment before joining.")
    # A payment rail named in a demand context is the same signal arriving in a
    # different shape ("send Rs 750 to this UPI"). Named on its own it is not a
    # signal at all, which is the whole correction here.
    elif _mentions_payment_demand(haystack):
        risk_score += 55
        reasons.append("Asks the candidate to transfer money through a payment app.")

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
