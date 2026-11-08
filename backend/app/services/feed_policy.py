"""Shared, deterministic feed admission and routing for ingestion and SQL reads."""

from __future__ import annotations

import re
from typing import Any, Mapping


TYPE_ALIASES = {
    alias: canonical
    for canonical in (
        "Hiring Challenge", "Internship", "Job", "Competition", "Hackathon",
        "Workshop", "Conference", "Scholarship", "Fellowship", "Research",
        "Opportunity", "Bounty", "Grant", "Webinar", "Bootcamp",
    )
    for alias in (canonical.lower(), canonical.lower() + "s")
}
TYPE_ALIASES["bounties"] = "Bounty"
TYPE_ALIASES["opportunities"] = "Opportunity"
TYPE_PORTALS = {
    **dict.fromkeys(("Hiring Challenge", "Internship", "Job"), "career"),
    **dict.fromkeys(("Competition", "Hackathon", "Workshop", "Conference", "Webinar", "Bootcamp"), "competitive"),
    **dict.fromkeys(("Scholarship", "Fellowship", "Research", "Bounty", "Grant"), "other"),
}
ROLE_PATTERN = r"\b(intern|internship|engineer|developer|analyst|scientist|designer|manager|consultant|associate|specialist|architect|coordinator|trainee|assistant|researcher|recruiter|accountant|writer|editor|technician|officer|executive|representative|apprentice)\b"
ROLE_END_PATTERN = ROLE_PATTERN + r"\s*(\([^)]*\))?$"
SENIOR_TITLE_PATTERN = r"\b(senior|sr\.?|staff|principal|director|head of|vice president|vp)\b"
EVENT_TYPES = (
    ("Hackathon", r"\b(hackathons?|buildathons?|datathons?|ideathons?|ctf)\b"),
    ("Workshop", r"\b(workshops?|bootcamps?|webinars?)\b"),
    ("Conference", r"\b(conferences?|symposiums?|summits?)\b"),
    ("Competition", r"\b(competitions?|challenges?|contests?|quizzes|quiz|olympiads?)\b"),
)
TITLE_RULES = (
    ("navigation_title", r"^(or\s+)?(see|view|browse|explore|find|search|discover)\s+(all\s+|more\s+|other\s+)?(remote\s+|student\s+|available\s+)?(jobs?|internships?|opportunities|roles|categories|hackathons?|competitions?)\b"),
    ("navigation_title", r"^(apply now|register now|learn more|read more|view details|sign in|sign up|post a job|host a|host your)\b"),
    ("category_title", r"^(all |campus |office |virtual |remote |summer |winter |upcoming |past |open |featured |popular )*(jobs?|internships?|opportunities|careers?|hackathons|competitions|workshops|conferences|challenges)$"),
    ("category_title", r"^(software development|web development|mechanical engineering|civil engineering|electrical engineering|computer science|information technology|data science|digital marketing|human resources|finance|marketing|sales|operations|engineering|management|consulting|research)$"),
    ("facet_title", r"^(entry level|experienced|management|senior level|executive level|full time|part time|permanent|temporary|contract|remote|internships?|jobs?)[\s\-:]*\d+$"),
    ("portal_title", r"^(internshala|unstop|devfolio|devpost|hack2skill|hackerearth|hackerrank|linkedin|indeed|naukri|glassdoor|wellfound|tensorhack|handshake|wayup)(\s+(jobs?|internships?|opportunities|careers?|portal|home))*$"),
    ("portal_title", r"\b(jobs?|internships?|opportunities|careers?)\s+(portal|board|directory|listings)$"),
    ("portal_title", r"\b(careers|career opportunities|internship opportunities)$"),
    ("markup_title", r"<[^>]+>"),
)
URL_RULES = (
    ("non_posting_url", r"^https?://(support|help|info|docs|blog|news)\."),
    ("non_posting_url", r"^https?://[^/]+/(login|signin|sign-in|signup|sign-up|register|logout|help|support|faq|contact|about|privacy|terms|pricing|news|stories|press|blog|guides|resources|newsroom|salaries|browse|explore|directory|search)([/._?#]|$)"),
    ("listing_page_url", r"^https?://[^/]+/(jobs?|internships?|careers?|opportunities|hackathons?|competitions?|workshops?|conferences?)/?([?#].*)?$"),
    ("listing_page_url", r"^https?://[^/]+/(jobs?|internships?|careers?)/(search|all|categories|remote|india)/?([?#].*)?$"),
    ("listing_page_url", r"^https?://(jobs\.lever\.co|jobs\.ashbyhq\.com|job-boards\.greenhouse\.io|boards\.greenhouse\.io)/[^/?#]+/?([?#].*)?$"),
)
DETAIL_QUERY_PATTERN = r"[?&](jk|gh_jid|job_?id|job|vacancy_?id|opportunity_?id|event_?id)=[a-z0-9][^&#]*"
VALID_URL_PATTERN = r"^https?://[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(:[0-9]+)?([/?#][^\s]*)?$"
BARE_URL_PATTERN = r"^https?://[^/?#]+/?([?#].*)?$"
PORTAL_HOST_PATTERN = r"^https?://(www\.)?(internshala\.com|unstop\.com|devfolio\.co|devpost\.com|hack2skill\.com|hackerearth\.com|hackerrank\.com|linkedin\.com|indeed\.com|naukri\.com|glassdoor\.com|wellfound\.com|tensorhack\.com)([/?#]|$)"


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def canonical_type(value: str | None) -> str | None:
    candidate = _text(value)
    return TYPE_ALIASES.get(candidate, candidate.title()) if candidate else None


def resolved_type(opportunity_type: str | None, title: str | None) -> str:
    name = _text(title)
    supplied = canonical_type(opportunity_type)
    if re.search(r"\bhiring challenges?\b", name):
        return "Hiring Challenge"
    if re.search(r"\b(bount(y|ies)|grants?|open calls?)\b", name) and not re.search(ROLE_PATTERN, name):
        return "Bounty" if re.search(r"\bbount(y|ies)\b", name) else "Grant"
    if not re.search(ROLE_END_PATTERN, name):
        for kind, pattern in EVENT_TYPES:
            if re.search(pattern, name):
                return kind
    if re.search(r"\bintern(ship|s)?\b", name):
        return "Internship"
    if re.search(SENIOR_TITLE_PATTERN, name) and re.search(ROLE_PATTERN, name):
        return "Job"
    if re.search(ROLE_END_PATTERN, name) and supplied not in {"Internship", "Job", "Hiring Challenge"}:
        return "Job"
    if supplied and supplied != "Opportunity":
        return supplied
    if re.search(ROLE_PATTERN, name):
        return "Job"
    return supplied or "Opportunity"


def resolve_portal(opportunity_type: str | None, title: str | None, portal_category: str | None = None) -> str:
    kind = resolved_type(opportunity_type, title)
    if kind in TYPE_PORTALS:
        return TYPE_PORTALS[kind]
    explicit = _text(portal_category)
    return explicit if explicit in {"career", "competitive", "other"} else "other"


def listing_rejection_reason(record: Mapping[str, Any], *, allowed_types: list[str] | None = None) -> str | None:
    title = _text(record.get("title"))
    url = _text(record.get("url"))
    if len(title) < 4:
        return "missing_title"
    if not re.fullmatch(VALID_URL_PATTERN, url):
        return "invalid_url"
    for reason, pattern in TITLE_RULES:
        if re.search(pattern, title):
            return reason
    source = re.sub(r"[^a-z0-9]", "", _text(record.get("source")))
    if source and re.sub(r"[^a-z0-9]", "", title) == source:
        return "portal_title"
    has_detail = bool(re.search(DETAIL_QUERY_PATTERN, url))
    for reason, pattern in URL_RULES:
        if re.search(pattern, url) and not (reason == "listing_page_url" and has_detail):
            return reason
    named_event = resolve_portal(record.get("opportunity_type"), title) == "competitive"
    if re.search(BARE_URL_PATTERN, url) and not has_detail:
        if not named_event or re.search(PORTAL_HOST_PATTERN, url):
            return "portal_homepage"
    if _text(record.get("url_liveness_status")) == "dead":
        return "dead_url"
    if resolved_type(record.get("opportunity_type"), title) == "Job" and re.search(SENIOR_TITLE_PATTERN, title):
        return "senior_role"
    if allowed_types and resolved_type(record.get("opportunity_type"), title) not in {canonical_type(value) for value in allowed_types}:
        return "out_of_scope"
    return None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _match(expression: str, pattern: str) -> str:
    return f"({expression} ~ {_literal(pattern.replace(chr(92) + 'b', chr(92) + 'y'))})"


TITLE_SQL = "lower(btrim(regexp_replace(coalesce(title, ''), '\\s+', ' ', 'g')))"
URL_SQL = "lower(btrim(coalesce(url, '')))"
TYPE_SQL = "lower(btrim(coalesce(opportunity_type, '')))"


def resolved_type_sql() -> str:
    canonical = "CASE " + " ".join(
        f"WHEN {TYPE_SQL} = {_literal(alias)} THEN {_literal(kind)}" for alias, kind in TYPE_ALIASES.items()
    ) + f" ELSE initcap({TYPE_SQL}) END"
    branches = [
        f"WHEN {_match(TITLE_SQL, r'\bhiring challenges?\b')} THEN 'Hiring Challenge'",
        f"WHEN {_match(TITLE_SQL, r'\bbount(y|ies)\b')} AND NOT {_match(TITLE_SQL, ROLE_PATTERN)} THEN 'Bounty'",
        f"WHEN {_match(TITLE_SQL, r'\b(grants?|open calls?)\b')} AND NOT {_match(TITLE_SQL, ROLE_PATTERN)} THEN 'Grant'",
    ]
    branches.extend(
        f"WHEN {_match(TITLE_SQL, pattern)} AND NOT {_match(TITLE_SQL, ROLE_END_PATTERN)} THEN {_literal(kind)}"
        for kind, pattern in EVENT_TYPES
    )
    branches.extend([
        f"WHEN {_match(TITLE_SQL, r'\bintern(ship|s)?\b')} THEN 'Internship'",
        f"WHEN {_match(TITLE_SQL, SENIOR_TITLE_PATTERN)} AND {_match(TITLE_SQL, ROLE_PATTERN)} THEN 'Job'",
        f"WHEN {_match(TITLE_SQL, ROLE_END_PATTERN)} AND ({canonical}) NOT IN ('Internship', 'Job', 'Hiring Challenge') THEN 'Job'",
        f"WHEN {TYPE_SQL} NOT IN ('', 'opportunity', 'opportunities') THEN ({canonical})",
        f"WHEN {_match(TITLE_SQL, ROLE_PATTERN)} THEN 'Job'",
    ])
    return "CASE " + " ".join(branches) + " ELSE 'Opportunity' END"


def portal_sql() -> str:
    return "CASE (" + resolved_type_sql() + ") " + " ".join(
        f"WHEN {_literal(kind)} THEN {_literal(portal)}" for kind, portal in TYPE_PORTALS.items()
    ) + " ELSE CASE WHEN lower(btrim(coalesce(portal_category, ''))) IN ('career', 'competitive') THEN lower(btrim(portal_category)) ELSE 'other' END END"


def listing_quality_sql(allowed_types: list[str]) -> tuple[str, ...]:
    detail = _match(URL_SQL, DETAIL_QUERY_PATTERN)
    clauses = [f"length({TITLE_SQL}) >= 4", _match(URL_SQL, VALID_URL_PATTERN)]
    clauses.extend(f"NOT {_match(TITLE_SQL, pattern)}" for _, pattern in TITLE_RULES)
    clauses.append(f"regexp_replace({TITLE_SQL}, '[^a-z0-9]', '', 'g') <> regexp_replace(lower(coalesce(source, '')), '[^a-z0-9]', '', 'g')")
    for reason, pattern in URL_RULES:
        rejection = _match(URL_SQL, pattern)
        clauses.append(f"(NOT {rejection} OR {detail})" if reason == "listing_page_url" else f"NOT {rejection}")
    clauses.append(f"(NOT {_match(URL_SQL, BARE_URL_PATTERN)} OR {detail} OR (({portal_sql()}) = 'competitive' AND NOT {_match(URL_SQL, PORTAL_HOST_PATTERN)}))")
    clauses.append("coalesce(url_liveness_status, 'unknown') <> 'dead'")
    clauses.append(f"(NOT {_match(TITLE_SQL, SENIOR_TITLE_PATTERN)} OR ({resolved_type_sql()}) <> 'Job')")
    if allowed_types:
        values = ", ".join(_literal(canonical_type(value) or "") for value in allowed_types)
        clauses.append(f"({resolved_type_sql()}) IN ({values})")
    return tuple(clauses)
