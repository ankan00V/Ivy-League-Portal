from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class ApifyUnavailableError(RuntimeError):
    """Raised when the Apify actor cannot be used for this request."""


# Unstop's own markup yields a title and a link and little else, so the HTML
# scraper cannot recover a deadline, eligibility, or whether a listing charges a
# registration fee. The managed actor returns all three as structured fields.
_FIELD_MAP = {
    "title": "title",
    "url": "url",
    "organizer": "university",
    "deadline": "deadline",
    "eligibility": "eligibility",
    "location": "location",
}

_TYPE_BY_OPPORTUNITY_TYPE = {
    "hackathons": "Hackathon",
    "hackathon": "Hackathon",
    "internships": "Internship",
    "internship": "Internship",
    "jobs": "Job",
    "competitions": "Competition",
    "quizzes": "Competition",
    "scholarships": "Scholarship",
    "conferences": "Conference",
    "workshops": "Workshop",
}


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "null", "nan"} else text


def _parse_list_field(value: Any) -> list[str]:
    """The actor serialises lists as their Python repr, e.g. "['Undergraduate']"."""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _clean(value)
    if not text:
        return []
    return [part.strip().strip("'\"") for part in re.findall(r"'([^']*)'|\"([^\"]*)\"", text) for part in part if part] or [text]


def _parse_deadline(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def charges_registration_fee(raw: dict[str, Any]) -> bool:
    """A paid registration is the strongest scam signal this market has.

    The trust service looks for fee demands in free text; Unstop states it
    outright, so surface it rather than hoping the description mentions it.
    """
    fee = _clean(raw.get("registrationFee")).lower()
    if not fee or fee in {"free", "0", "no", "none"}:
        return False
    return not re.fullmatch(r"(?:rs\.?|inr|₹)?\s*0+(?:\.0+)?", fee)


def map_actor_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one actor row into the scraper's opportunity shape."""
    title = _clean(raw.get("title"))
    url = _clean(raw.get("url"))
    if not title or not url:
        return None

    opportunity_type = _TYPE_BY_OPPORTUNITY_TYPE.get(
        _clean(raw.get("opportunityType")).lower(), "Opportunity"
    )
    eligibility_parts = _parse_list_field(raw.get("eligibility"))
    # "All" is Unstop's placeholder for no restriction and carries no signal.
    eligibility = ", ".join(p for p in eligibility_parts if p.lower() != "all")

    tags = _parse_list_field(raw.get("tags"))
    mode = _clean(raw.get("mode")).lower()
    work_mode = {"online": "Remote", "offline": "Onsite", "hybrid": "Hybrid"}.get(mode)

    description_bits = [
        f"Organised by {_clean(raw.get('organizer'))}." if _clean(raw.get("organizer")) else "",
        f"Prize: {_clean(raw.get('prize'))}." if _clean(raw.get("prize")) else "",
        f"Eligibility: {eligibility}." if eligibility else "",
        f"Registration fee: {_clean(raw.get('registrationFee'))}." if _clean(raw.get("registrationFee")) else "",
        f"Registrations so far: {_clean(raw.get('registrationCount'))}." if _clean(raw.get("registrationCount")) else "",
    ]

    return {
        "title": title,
        "url": url,
        "university": _clean(raw.get("organizer")) or "Unstop",
        "source": "unstop_apify",
        "opportunity_type": opportunity_type,
        "description": " ".join(bit for bit in description_bits if bit).strip(),
        "deadline": _parse_deadline(raw.get("deadline")),
        "eligibility": eligibility or None,
        "location": _clean(raw.get("location")) or None,
        "work_mode": work_mode,
        "tags": tags,
        # Unstop reports whether the listing is still open, so this is a real
        # observation rather than the "unknown" every other source records.
        "url_liveness_status": "live" if _clean(raw.get("status")).lower() == "live" else "unknown",
        "charges_registration_fee": charges_registration_fee(raw),
    }


class ApifyUnstopClient:
    """Fetches Unstop listings through a managed Apify actor."""

    @property
    def configured(self) -> bool:
        return bool(settings.APIFY_ENABLED and (settings.APIFY_API_TOKEN or "").strip())

    def fetch(self, opportunity_types: list[str] | None = None, max_results: int | None = None) -> list[dict[str, Any]]:
        if not self.configured:
            raise ApifyUnavailableError("apify_not_configured")
        try:
            from apify_client import ApifyClient
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ApifyUnavailableError("apify_client_missing") from exc

        client = ApifyClient((settings.APIFY_API_TOKEN or "").strip())
        run_input = {
            "opportunityTypes": opportunity_types or ["hackathons", "internships", "competitions"],
            "maxResults": int(max_results or settings.APIFY_UNSTOP_MAX_RESULTS),
        }
        run = client.actor(settings.APIFY_UNSTOP_ACTOR).call(
            run_input=run_input,
            timeout_secs=int(settings.APIFY_TIMEOUT_SECONDS),
        )
        dataset_id = getattr(run, "default_dataset_id", None) or (
            run.get("defaultDatasetId") if isinstance(run, dict) else None
        )
        if not dataset_id:
            raise ApifyUnavailableError("apify_run_returned_no_dataset")

        rows: list[dict[str, Any]] = []
        for item in client.dataset(dataset_id).iterate_items():
            mapped = map_actor_item(item if isinstance(item, dict) else {})
            if mapped:
                rows.append(mapped)
        logger.info("apify unstop actor returned %d usable rows", len(rows))
        return rows


apify_unstop_client = ApifyUnstopClient()
