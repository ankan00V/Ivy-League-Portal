"""Classify a listing into the feed's placement pills: india, international, remote, hybrid.

These four are **not mutually exclusive**, and that is deliberate. India/international
is geography; remote/hybrid is work mode. A remote internship based in Bengaluru is
genuinely both `india` and `remote`, and a student looking for either should find it
under either. Pill counts therefore sum to more than the corpus size, which is honest
rather than a bug — the alternative, forcing one bucket per listing, hides remote
Indian internships from the "India" pill, which is exactly where students look first.

The hard part is that the underlying data barely supports the question. Measured on
the live corpus (1,418 active listings, 2026-08-06):

- `work_mode` is **null on 1,042 rows (73%)**. Where present it is case-split
  (`Remote` 256 vs `remote` 23) and salted with values that are not work modes at
  all: `Intern`, `Full-time Employment`, `On-roll`, `Full Time Employee`.
- `location` is **null on 533 rows (38%)**. Some rows store a work mode in it
  (`In-Office` 16, `Hybrid` 7) and some store nothing usable (`2 Locations`).

So classification reads every field that might carry the signal, in decreasing order
of trustworthiness: the explicit `work_mode`, then `location` (because scrapers
demonstrably put modes there), then the title and description text. Text inference
recovers roughly 330 listings that would otherwise show under no work-mode pill at
all.

**Unknown is a real answer.** A listing we cannot place gets no geography pill and
appears only under "All". This is a deliberate departure from
`opportunity_quality_service.normalize_location`, which maps any remote listing to
`("India", "remote")` — that hardcodes the assumption that every remote job is
Indian, which is false and would push US remote roles into the India pill.
"""

from __future__ import annotations

import re
from typing import Iterable, Literal

FeedCategory = Literal["india", "international", "remote", "hybrid"]

#: Pill order as rendered in the UI. "all" is not stored on a listing; it is the
#: absence of a filter.
FEED_CATEGORIES: tuple[str, ...] = ("india", "remote", "hybrid", "international")


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _tokens(value: str) -> str:
    """Collapse punctuation so 'Bengaluru-VTP, India' and 'Ho Chi Minh, vn' tokenize."""
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _has_word(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _has_any(haystack: str, needles: Iterable[str]) -> bool:
    return any(_has_word(haystack, n) for n in needles)


# --- Work mode -------------------------------------------------------------

#: Values that appear in `work_mode` but describe employment type, not where the
#: work happens. Present in the live corpus and must not be read as a mode.
_NON_MODE_VALUES = {
    "intern",
    "internship",
    "full time",
    "full time employment",
    "full time employee",
    "fulltime",
    "part time",
    "on roll",
    "onroll",
    "contract",
    "permanent",
}

_REMOTE_TERMS = ("remote", "wfh", "work from home", "work from anywhere", "fully remote", "anywhere")
_HYBRID_TERMS = ("hybrid", "flexible working", "partially remote")
_ONSITE_TERMS = ("onsite", "on site", "in office", "in person", "on premise", "office based")

#: Phrases that mean the opposite of the term that follows them. Without this,
#: "this role is not remote" and "no work from home" would both be read as remote.
_NEGATIONS = ("no ", "not ", "non ", "never ", "isn t ", "is not ", "cannot ", "without ")


def _mentions(haystack: str, terms: Iterable[str]) -> bool:
    """True when a term appears and is not immediately negated."""
    for term in terms:
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack):
            prefix = haystack[max(0, match.start() - 14) : match.start()]
            if any(prefix.endswith(neg) for neg in _NEGATIONS):
                continue
            return True
    return False


def _explicit_mode(value: str) -> str | None:
    """Read a work mode from a field whose whole value is supposed to be one."""
    compact = _tokens(value)
    if not compact or compact in _NON_MODE_VALUES:
        return None
    if _has_any(compact, _REMOTE_TERMS):
        return "remote"
    if _has_any(compact, _HYBRID_TERMS):
        return "hybrid"
    if _has_any(compact, _ONSITE_TERMS):
        return "onsite"
    return None


# --- Geography -------------------------------------------------------------

_INDIA_TERMS = ("india", "indian", "bharat")

_INDIA_STATES = (
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa",
    "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal", "puducherry",
    "pondicherry", "jammu", "kashmir", "ladakh", "chandigarh", "andaman", "nicobar",
    "lakshadweep", "dadra", "daman", "diu",
)

_INDIA_CITIES = (
    "bangalore", "bengaluru", "blr", "mumbai", "bombay", "delhi", "new delhi",
    "delhi ncr", "ncr", "gurgaon", "gurugram", "noida", "greater noida", "hyderabad",
    "chennai", "madras", "kolkata", "calcutta", "pune", "ahmedabad", "jaipur",
    "lucknow", "indore", "bhopal", "nagpur", "coimbatore", "kochi", "cochin",
    "trivandrum", "thiruvananthapuram", "visakhapatnam", "vizag", "surat",
    "vadodara", "mysore", "mysuru", "mohali", "kanpur", "patna", "bhubaneswar",
    "guwahati", "dehradun", "ranchi", "raipur", "thane", "navi mumbai", "faridabad",
    "ghaziabad", "hosur", "manesar", "sonipat", "vellore", "warangal", "trichy",
    "tiruchirappalli", "madurai", "salem", "jalandhar", "ludhiana", "amritsar",
    "udaipur", "jodhpur", "kota", "gwalior", "varanasi", "prayagraj", "allahabad",
    "agra", "meerut", "aurangabad", "nashik", "rajkot", "jamshedpur", "durgapur",
    "siliguri", "shillong", "imphal",
)

#: Countries and territories other than India. Kept explicit rather than
#: "anything that is not India", because a third of location values are junk
#: (`2 Locations`, `In-Office`) and would otherwise be labelled international.
_INTERNATIONAL_COUNTRIES = (
    "usa", "u s a", "united states", "america", "canada", "mexico", "brazil",
    "argentina", "chile", "colombia", "uk", "u k", "united kingdom", "england",
    "scotland", "wales", "ireland", "france", "germany", "netherlands", "belgium",
    "spain", "portugal", "italy", "switzerland", "austria", "sweden", "norway",
    "denmark", "finland", "poland", "czech", "romania", "hungary", "greece",
    "turkey", "russia", "ukraine", "israel", "uae", "united arab emirates",
    "saudi arabia", "qatar", "kuwait", "bahrain", "oman", "egypt", "south africa",
    "kenya", "nigeria", "china", "japan", "south korea", "korea", "taiwan",
    "hong kong", "singapore", "malaysia", "indonesia", "thailand", "vietnam",
    "philippines", "australia", "new zealand", "bangladesh", "pakistan",
    "sri lanka", "nepal", "bhutan",
)

_INTERNATIONAL_CITIES = (
    "san francisco", "sf", "san jose", "new york", "nyc", "brooklyn", "seattle",
    "boston", "chicago", "austin", "los angeles", "la", "san diego", "denver",
    "atlanta", "dallas", "houston", "miami", "philadelphia", "washington", "dc",
    "toronto", "vancouver", "montreal", "london", "manchester", "dublin", "paris",
    "berlin", "munich", "hamburg", "amsterdam", "rotterdam", "brussels", "zurich",
    "geneva", "vienna", "stockholm", "oslo", "copenhagen", "helsinki", "warsaw",
    "prague", "lisbon", "madrid", "barcelona", "milan", "rome", "dubai",
    "abu dhabi", "doha", "riyadh", "tel aviv", "tokyo", "osaka", "seoul",
    "beijing", "shanghai", "shenzhen", "taipei", "sydney", "melbourne",
    "auckland", "ho chi minh", "hanoi", "jakarta", "bangkok", "manila",
    "kuala lumpur", "gerlingen", "cambridge", "oxford", "edinburgh",
)

#: Two-letter markers that only disambiguate when the string looks like a place.
#: `ca` is Canada/California but also a common substring, hence word-boundary use.
_INTERNATIONAL_CODES = (
    "ca", "ny", "tx", "wa", "ma", "il", "nj", "pa", "ga", "az", "co", "or", "nc",
    "va", "md", "mn", "mi", "oh", "fl", "ut", "vn", "de", "fr", "nl", "se", "ch",
    "jp", "sg", "au", "nz", "za",
)


#: Sources that only ever list Indian roles. Used as a last-resort geography hint
#: when the row itself carries no usable location.
#:
#: This is worth more than it looks. Measured 2026-08-06: Internshala had 70 of 82
#: listings unplaceable, Unstop 52 of 75, Naukri 8 of 8 — all of them Indian
#: internships whose `location` column was simply empty. Reading the source recovers
#: them at high precision, because these platforms do not carry non-Indian roles.
#:
#: Deliberately excludes global boards (linkedin, glassdoor, ycombinator_jobs,
#: devpost, codeforces) and US-centric ones (wayup, handshake, extern, ivy_rss),
#: where the same inference would be wrong.
_INDIA_ONLY_SOURCES = frozenset(
    {
        "internshala",
        "unstop",
        "naukri",
        "freshersworld",
        "indeed_india",
        "aicte_internship",
        "makeintern",
        "promilo",
        "techgig",
        "foundit",
        "hack2skill",
        "devfolio",
        "thejobcompany",
    }
)


def _geography(location: str, description: str) -> str | None:
    """Return 'india', 'international', or None when the listing cannot be placed."""
    loc = _tokens(location)

    if loc:
        if _has_any(loc, _INDIA_TERMS) or _has_any(loc, _INDIA_CITIES) or _has_any(loc, _INDIA_STATES):
            return "india"
        if (
            _has_any(loc, _INTERNATIONAL_COUNTRIES)
            or _has_any(loc, _INTERNATIONAL_CITIES)
            or _has_any(loc, _INTERNATIONAL_CODES)
        ):
            return "international"

    # Only fall through to free text when the location field said nothing useful,
    # and only for India — a description mentioning "our London office" on an Indian
    # listing is far more common than the reverse.
    body = _tokens(description)
    if body and (_has_any(body, _INDIA_TERMS) or _has_any(body, _INDIA_CITIES)):
        return "india"
    return None


# --- Public API ------------------------------------------------------------


def classify_placement(
    *,
    location: object = None,
    work_mode: object = None,
    title: object = None,
    description: object = None,
    source: object = None,
) -> list[str]:
    """Return the pills a listing belongs to, in `FEED_CATEGORIES` order.

    May return an empty list. A listing with no usable location and no work-mode
    signal is genuinely unplaceable, and inventing a pill for it would put wrong
    listings in front of students. It still appears under "All".
    """
    location_text = _norm(location)
    work_mode_text = _norm(work_mode)
    body = _tokens(" ".join([_norm(title), _norm(description)]))

    categories: set[str] = set()

    # Work mode, most trustworthy source first.
    mode = _explicit_mode(work_mode_text)
    if mode is None:
        # Scrapers put 'Hybrid' and 'In-Office' in the location column often enough
        # to be worth reading, and it never costs us a real geography match because
        # those values carry no place name.
        mode = _explicit_mode(location_text)
    if mode is None and body:
        if _mentions(body, _REMOTE_TERMS):
            mode = "remote"
        elif _mentions(body, _HYBRID_TERMS):
            mode = "hybrid"

    if mode in {"remote", "hybrid"}:
        categories.add(mode)

    geography = _geography(location_text, _norm(description))
    if geography is None and _norm(source) in _INDIA_ONLY_SOURCES:
        # Last resort, and only when the row said nothing itself: an India-only
        # board cannot be listing a role anywhere else.
        geography = "india"
    if geography:
        categories.add(geography)

    return [c for c in FEED_CATEGORIES if c in categories]
