from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pymongo.errors import DuplicateKeyError

from app.core.time import utc_now
from app.models.opportunity import Opportunity
from app.models.post import Post
from app.models.source_discovery import (
    CompanySeed,
    DiscoveredSource,
    DiscoveryMethod,
    ScraperRegistration,
    ScraperRegistrationStatus,
    SourceStatus,
)
from app.models.user import User
from app.services.ai_engine import ai_system
from app.services.scraper import _insert_and_broadcast
from app.services.source_discovery import (
    FetchedPage,
    SourceHttpClient,
    normalize_domain,
    normalize_url,
    source_key_from_domain,
)


EARLY_CAREER_TERMS = {
    "intern",
    "internship",
    "student",
    "students",
    "university",
    "campus",
    "graduate",
    "new grad",
    "new graduate",
    "entry level",
    "entry-level",
    "fresher",
    "freshers",
    "trainee",
    "apprentice",
    "associate software engineer",
}

EXPERIENCED_TERMS = {
    "senior",
    "staff",
    "principal",
    "manager",
    "director",
    "lead ",
    "architect",
    "10+ years",
    "8+ years",
    "7+ years",
    "6+ years",
    "5+ years",
    "4+ years",
    "3+ years",
}


@dataclass(frozen=True)
class AtsEndpoint:
    method: str
    slug: str
    url: str
    confidence: float
    source_hint: str


@dataclass
class CompanyCareersReport:
    company: str
    domain: str
    careers_url: str | None
    endpoints_checked: int = 0
    endpoint_hits: list[str] = field(default_factory=list)
    fetched: int = 0
    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    failed: int = 0
    out_of_scope: int = 0
    errors: list[str] = field(default_factory=list)
    scraper_key: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "domain": self.domain,
            "careers_url": self.careers_url,
            "endpoints_checked": self.endpoints_checked,
            "endpoint_hits": self.endpoint_hits,
            "fetched": self.fetched,
            "parsed": self.parsed,
            "inserted": self.inserted,
            "updated": self.updated,
            "failed": self.failed,
            "out_of_scope": self.out_of_scope,
            "errors": self.errors[:10],
            "scraper_key": self.scraper_key,
        }


def _slug_variants(company_name: str, domain: str) -> list[str]:
    raw = [
        company_name,
        domain.split(".", 1)[0],
        company_name.replace("&", "and"),
        company_name.replace("'", ""),
    ]
    variants: list[str] = []
    seen: set[str] = set()
    for value in raw:
        compact = re.sub(r"[^a-z0-9]+", "", value.lower())
        dashed = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        underscored = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        for candidate in [compact, dashed, underscored]:
            if candidate and candidate not in seen:
                variants.append(candidate)
                seen.add(candidate)
    return variants[:6]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_title(value: Any, *, company_name: str | None = None) -> str:
    raw = _text(value)
    if not raw:
        return ""
    tokens = raw.split()
    collapsed: list[str] = []
    for token in tokens:
        if collapsed and collapsed[-1].lower() == token.lower():
            continue
        if token.lower().endswith("_hat"):
            continue
        collapsed.append(token)
    title = " ".join(collapsed).strip(" -|")
    generic = {"students", "student", "careers", "jobs", "early careers", "internships"}
    if company_name and title.lower() in generic:
        if "intern" in title.lower() or "student" in title.lower():
            return f"{company_name} Student and Internship Programs"
        return f"{company_name} Early Careers"
    return title[:180]


def _is_early_career(row: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            _text(row.get("title")),
            _text(row.get("description")),
            _text(row.get("description_preview")),
            " ".join(str(tag) for tag in list(row.get("tags") or [])),
        ]
    ).lower()
    if not haystack:
        return False
    if any(term in haystack for term in EARLY_CAREER_TERMS):
        return not any(term in haystack for term in EXPERIENCED_TERMS)
    return False


def _stable_source_id(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:32]


def _priority_rank(seed: CompanySeed) -> int:
    tier = str(getattr(seed, "priority_tier", "") or "").strip().lower()
    if tier in {"tier_1", "tier 1", "dream"}:
        return 0
    if tier in {"tier_2", "tier 2", "high"}:
        return 1
    if tier in {"tier_3", "tier 3", "standard"}:
        return 2
    return 3


def _seed_due_sort_key(seed: CompanySeed, now: datetime | None = None) -> tuple[int, int, datetime]:
    checked_at = getattr(seed, "last_checked_at", None)
    if checked_at is not None and checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    current = now or utc_now()
    cadence_seconds = max(1, int(getattr(seed, "check_cadence_hours", 168) or 168)) * 3600
    is_due = checked_at is None or (current - checked_at).total_seconds() >= cadence_seconds
    return (0 if is_due else 1, _priority_rank(seed), checked_at or datetime.min.replace(tzinfo=timezone.utc))


class CompanyCareersIntelligenceService:
    def __init__(
        self,
        *,
        http_client: SourceHttpClient | None = None,
        max_endpoint_candidates: int = 14,
    ) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=10)
        self.max_endpoint_candidates = max(3, int(max_endpoint_candidates))

    async def ingest_seeded_company_careers(
        self,
        *,
        limit: int = 25,
        company_names: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        requested_names = {item.strip().lower() for item in list(company_names or []) if item.strip()}
        if requested_names:
            rows = await CompanySeed.find_many(
                CompanySeed.student_friendly == True,  # noqa: E712
            ).to_list()
            rows = [row for row in rows if row.company_name.strip().lower() in requested_names]
        else:
            rows = await CompanySeed.find_many(
                CompanySeed.student_friendly == True,  # noqa: E712
            ).to_list()
            rows = sorted(rows, key=_seed_due_sort_key)[: max(1, int(limit) * 3)]
        rows = rows[: max(1, int(limit))]

        system_user = await User.find_one({"is_admin": True})
        system_user_id = system_user.id if system_user else None

        semaphore = asyncio.Semaphore(4)

        async def run_one(seed: CompanySeed) -> CompanyCareersReport:
            async with semaphore:
                return await self.ingest_company_seed(seed, system_user_id=system_user_id, dry_run=dry_run)

        reports = await asyncio.gather(*(run_one(seed) for seed in rows), return_exceptions=True)
        normalized_reports: list[dict[str, Any]] = []
        for seed, report in zip(rows, reports):
            if isinstance(report, Exception):
                normalized_reports.append(
                    CompanyCareersReport(
                        company=seed.company_name,
                        domain=seed.domain,
                        careers_url=seed.careers_url,
                        errors=[str(report)],
                    ).as_dict()
                )
            else:
                normalized_reports.append(report.as_dict())

        totals = {
            "companies_checked": len(normalized_reports),
            "endpoint_hits": sum(len(item["endpoint_hits"]) for item in normalized_reports),
            "fetched": sum(int(item["fetched"]) for item in normalized_reports),
            "parsed": sum(int(item["parsed"]) for item in normalized_reports),
            "inserted": sum(int(item["inserted"]) for item in normalized_reports),
            "updated": sum(int(item["updated"]) for item in normalized_reports),
            "failed": sum(int(item["failed"]) for item in normalized_reports),
            "out_of_scope": sum(int(item["out_of_scope"]) for item in normalized_reports),
        }
        return {
            "status": "ok",
            "dry_run": bool(dry_run),
            **totals,
            "reports": normalized_reports,
        }

    async def ingest_company_seed(
        self,
        seed: CompanySeed,
        *,
        system_user_id: Any = None,
        dry_run: bool = False,
    ) -> CompanyCareersReport:
        report = CompanyCareersReport(
            company=seed.company_name,
            domain=seed.domain,
            careers_url=seed.careers_url,
        )
        endpoints = await self.discover_ats_endpoints(seed)
        report.endpoints_checked = len(endpoints)

        rows: list[dict[str, Any]] = []
        successful_endpoint: AtsEndpoint | None = None
        for endpoint in endpoints:
            try:
                endpoint_rows = await self.fetch_endpoint(seed, endpoint)
                report.fetched += len(endpoint_rows)
                filtered = [row for row in endpoint_rows if _is_early_career(row)]
                rows.extend(filtered)
                report.out_of_scope += max(0, len(endpoint_rows) - len(filtered))
                if endpoint_rows:
                    report.endpoint_hits.append(endpoint.source_hint)
                if filtered and successful_endpoint is None:
                    successful_endpoint = endpoint
            except Exception as exc:
                report.errors.append(f"{endpoint.source_hint}:{exc}")

        if not rows and seed.careers_url:
            try:
                page = await self.http_client.fetch(seed.careers_url, timeout_seconds=10, render=True)
                page_rows = self.extract_official_page_links(seed, page)
                report.fetched += len(page_rows)
                filtered = [row for row in page_rows if _is_early_career(row)]
                rows.extend(filtered)
                report.out_of_scope += max(0, len(page_rows) - len(filtered))
                if filtered:
                    report.endpoint_hits.append("official_page_heuristic")
            except Exception as exc:
                report.errors.append(f"official_page:{exc}")

        report.parsed = len(rows)
        if dry_run:
            seed.last_checked_at = utc_now()
            seed.updated_at = utc_now()
            await seed.save()
            return report

        if successful_endpoint is not None:
            report.scraper_key = await self.register_successful_source(seed, successful_endpoint)

        if rows:
            opportunities = [self.to_ingestion_payload(seed, row) for row in rows]
            stats = await _insert_and_broadcast(
                opportunities=opportunities,
                source_name=f"{seed.company_name} Careers",
                system_user_id=system_user_id,
                ai_system=ai_system,
                Opportunity=Opportunity,
                Post=Post,
            )
            report.inserted = int(stats.get("inserted") or 0)
            report.updated = int(stats.get("updated") or 0)
            report.failed = int(stats.get("failed") or 0)
            report.out_of_scope += int(stats.get("out_of_scope") or 0)

        seed.last_checked_at = utc_now()
        seed.updated_at = utc_now()
        await seed.save()
        return report

    async def discover_ats_endpoints(self, seed: CompanySeed) -> list[AtsEndpoint]:
        candidates: list[AtsEndpoint] = []
        for slug in _slug_variants(seed.company_name, seed.domain):
            candidates.extend(
                [
                    AtsEndpoint(
                        method="greenhouse",
                        slug=slug,
                        url=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                        confidence=0.75,
                        source_hint=f"greenhouse:{slug}",
                    ),
                    AtsEndpoint(
                        method="lever",
                        slug=slug,
                        url=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                        confidence=0.75,
                        source_hint=f"lever:{slug}",
                    ),
                    AtsEndpoint(
                        method="ashby",
                        slug=slug,
                        url=f"https://api.ashbyhq.com/posting-public/jobs?organizationHostedJobsPageName={slug}",
                        confidence=0.72,
                        source_hint=f"ashby:{slug}",
                    ),
                    AtsEndpoint(
                        method="smartrecruiters",
                        slug=slug,
                        url=f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
                        confidence=0.68,
                        source_hint=f"smartrecruiters:{slug}",
                    ),
                ]
            )
        if seed.careers_url:
            try:
                page = await self.http_client.fetch(seed.careers_url, timeout_seconds=8, render=True)
                candidates = self._endpoints_from_page(page) + candidates
            except Exception:
                pass

        deduped: list[AtsEndpoint] = []
        seen: set[str] = set()
        for endpoint in candidates:
            if endpoint.url in seen:
                continue
            seen.add(endpoint.url)
            deduped.append(endpoint)
            if len(deduped) >= self.max_endpoint_candidates:
                break
        return deduped

    def _endpoints_from_page(self, page: FetchedPage) -> list[AtsEndpoint]:
        haystack = f"{page.final_url}\n{page.text}"
        endpoints: list[AtsEndpoint] = []
        patterns = [
            ("greenhouse", r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-z0-9_-]+)"),
            ("lever", r"jobs\.lever\.co/([a-z0-9_-]+)"),
            ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_-]+)"),
        ]
        for method, pattern in patterns:
            for match in re.finditer(pattern, haystack, flags=re.I):
                slug = match.group(1).strip()
                if method == "greenhouse":
                    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
                elif method == "lever":
                    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
                else:
                    url = f"https://api.ashbyhq.com/posting-public/jobs?organizationHostedJobsPageName={slug}"
                endpoints.append(
                    AtsEndpoint(method=method, slug=slug, url=url, confidence=0.9, source_hint=f"{method}:{slug}:page")
                )
        return endpoints

    async def fetch_endpoint(self, seed: CompanySeed, endpoint: AtsEndpoint) -> list[dict[str, Any]]:
        page = await self.http_client.fetch(endpoint.url, timeout_seconds=10)
        if page.status_code >= 400:
            raise RuntimeError(f"http_{page.status_code}")
        payload = json.loads(page.text or "{}")
        if endpoint.method == "greenhouse":
            return self._map_greenhouse(seed, payload)
        if endpoint.method == "lever":
            return self._map_lever(seed, payload)
        if endpoint.method == "ashby":
            return self._map_ashby(seed, payload)
        if endpoint.method == "smartrecruiters":
            return self._map_smartrecruiters(seed, payload)
        return []

    def extract_official_page_links(self, seed: CompanySeed, page: FetchedPage) -> list[dict[str, Any]]:
        soup = BeautifulSoup(page.text or "", "html.parser")
        rows: list[dict[str, Any]] = []
        for link in soup.select("a[href]")[:250]:
            text = _text(link.get_text(" ", strip=True))
            href = str(link.get("href") or "").strip()
            if not text or not href:
                continue
            text_lower = text.lower()
            if not any(term in text_lower for term in EARLY_CAREER_TERMS):
                continue
            title = _clean_title(text, company_name=seed.company_name)
            rows.append(
                {
                    "title": title,
                    "company": seed.company_name,
                    "location": None,
                    "work_mode": "Remote" if "remote" in text_lower else None,
                    "apply_url": normalize_url(urljoin(page.final_url, href)),
                    "description": (
                        f"{title} discovered on the official {seed.company_name} careers site. "
                        "This listing was captured from a trusted company-owned early-career page."
                    ),
                    "description_preview": text[:220],
                    "tags": ["official careers", "early career"],
                    "opportunity_type": "Internship" if "intern" in text_lower else "Job",
                }
            )
            if len(rows) >= 10:
                break
        return rows

    def _map_greenhouse(self, seed: CompanySeed, payload: Any) -> list[dict[str, Any]]:
        return [
            {
                "title": row.get("title"),
                "company": seed.company_name,
                "location": (row.get("location") or {}).get("name"),
                "apply_url": row.get("absolute_url"),
                "description": BeautifulSoup(str(row.get("content") or ""), "html.parser").get_text(" ", strip=True),
                "description_preview": BeautifulSoup(str(row.get("content") or ""), "html.parser").get_text(" ", strip=True)[:240],
                "tags": [item.get("name") for item in row.get("departments", []) if item.get("name")],
                "opportunity_type": "Internship" if "intern" in str(row.get("title") or "").lower() else "Job",
                "posted_date_text": row.get("updated_at"),
            }
            for row in list((payload or {}).get("jobs") or [])
            if row.get("title") and row.get("absolute_url")
        ]

    def _map_lever(self, seed: CompanySeed, payload: Any) -> list[dict[str, Any]]:
        rows = payload if isinstance(payload, list) else []
        return [
            {
                "title": row.get("text"),
                "company": seed.company_name,
                "location": (row.get("categories") or {}).get("location"),
                "work_mode": (row.get("categories") or {}).get("commitment"),
                "apply_url": row.get("hostedUrl"),
                "description": BeautifulSoup(str(row.get("descriptionPlain") or row.get("description") or ""), "html.parser").get_text(" ", strip=True),
                "description_preview": BeautifulSoup(str(row.get("descriptionPlain") or row.get("description") or ""), "html.parser").get_text(" ", strip=True)[:240],
                "tags": [
                    item
                    for item in [
                        (row.get("categories") or {}).get("team"),
                        (row.get("categories") or {}).get("department"),
                        (row.get("categories") or {}).get("commitment"),
                    ]
                    if item
                ],
                "opportunity_type": "Internship" if "intern" in str(row.get("text") or "").lower() else "Job",
                "posted_date_text": row.get("createdAt"),
            }
            for row in rows
            if row.get("text") and row.get("hostedUrl")
        ]

    def _map_ashby(self, seed: CompanySeed, payload: Any) -> list[dict[str, Any]]:
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        return [
            {
                "title": row.get("title"),
                "company": seed.company_name,
                "location": row.get("locationName"),
                "apply_url": row.get("jobUrl"),
                "description": BeautifulSoup(str(row.get("descriptionHtml") or ""), "html.parser").get_text(" ", strip=True),
                "description_preview": BeautifulSoup(str(row.get("descriptionHtml") or ""), "html.parser").get_text(" ", strip=True)[:240],
                "tags": [row.get("departmentName")] if row.get("departmentName") else [],
                "opportunity_type": "Internship" if "intern" in str(row.get("title") or "").lower() else "Job",
            }
            for row in list(jobs or [])
            if row.get("title") and row.get("jobUrl")
        ]

    def _map_smartrecruiters(self, seed: CompanySeed, payload: Any) -> list[dict[str, Any]]:
        rows = payload.get("content") if isinstance(payload, dict) else []
        return [
            {
                "title": row.get("name"),
                "company": seed.company_name,
                "location": _text((row.get("location") or {}).get("city") or (row.get("location") or {}).get("region")),
                "apply_url": (row.get("ref") or row.get("url")),
                "description": row.get("name"),
                "description_preview": row.get("name"),
                "tags": [item for item in [row.get("department", {}).get("label") if isinstance(row.get("department"), dict) else None] if item],
                "opportunity_type": "Internship" if "intern" in str(row.get("name") or "").lower() else "Job",
                "posted_date_text": row.get("releasedDate"),
            }
            for row in list(rows or [])
            if row.get("name") and (row.get("ref") or row.get("url"))
        ]

    def to_ingestion_payload(self, seed: CompanySeed, row: dict[str, Any]) -> dict[str, Any]:
        title = _text(row.get("title"))
        apply_url = normalize_url(str(row.get("apply_url") or row.get("url")))
        description = _text(row.get("description")) or _text(row.get("description_preview")) or title
        return {
            "title": title,
            "description": description,
            "url": apply_url,
            "opportunity_type": _text(row.get("opportunity_type")) or "Job",
            "university": seed.company_name,
            "source": f"company_careers_{normalize_domain(seed.domain).replace('.', '_')}",
            "source_id": _stable_source_id(seed.domain, title, apply_url),
            "domain": seed.industry,
            "location": row.get("location"),
            "work_mode": row.get("work_mode"),
            "tags": sorted({str(item).strip().lower() for item in list(row.get("tags") or []) if str(item).strip()} | {"official careers"}),
            "eligibility": "Early-career, student, internship, graduate, trainee, or fresher opportunity from an official company careers source.",
        }

    async def register_successful_source(self, seed: CompanySeed, endpoint: AtsEndpoint) -> str:
        source_url = seed.careers_url or endpoint.url
        domain = normalize_domain(seed.domain)
        source = await DiscoveredSource.find_one(DiscoveredSource.domain == domain)
        if source is None:
            source = DiscoveredSource(
                url=source_url,
                domain=domain,
                name=seed.company_name,
                source_type="company_careers",
                discovery_method=DiscoveryMethod.company_seed,
                discovery_query=seed.company_name,
                discovered_by="company_careers_intelligence",
                status=SourceStatus.promoted,
                qualification_score=95,
                extraction_confidence=endpoint.confidence,
                parser_template={
                    "extraction_method": f"ats_{endpoint.method}",
                    "ats_slug": endpoint.slug,
                    "ats_endpoint_url": endpoint.url,
                    "official_company_seed": True,
                },
                trust_score=90,
                promoted_at=utc_now(),
                promoted_by="company_careers_intelligence",
            )
            try:
                await source.insert()
            except DuplicateKeyError:
                source = await DiscoveredSource.find_one(DiscoveredSource.domain == domain)
        else:
            source.status = SourceStatus.promoted
            source.name = seed.company_name
            source.source_type = "company_careers"
            source.extraction_confidence = endpoint.confidence
            source.parser_template = {
                "extraction_method": f"ats_{endpoint.method}",
                "ats_slug": endpoint.slug,
                "ats_endpoint_url": endpoint.url,
                "official_company_seed": True,
            }
            source.trust_score = max(float(source.trust_score or 0), 90)
            source.updated_at = utc_now()
            await source.save()

        scraper_key = source_key_from_domain(domain, "company_careers")
        registration = await ScraperRegistration.find_one(ScraperRegistration.scraper_key == scraper_key)
        payload = {
            "scraper_key": scraper_key,
            "source_name": f"{seed.company_name} Careers",
            "domain": domain,
            "careers_url": source_url,
            "source_type": "company_careers",
            "extraction_method": f"ats_{endpoint.method}",
            "parser_template": {
                "extraction_method": f"ats_{endpoint.method}",
                "ats_slug": endpoint.slug,
                "ats_endpoint_url": endpoint.url,
                "official_company_seed": True,
            },
            "trust_score": 90.0,
            "status": ScraperRegistrationStatus.active,
            "discovered_source_id": str(source.id) if source else None,
            "is_original_source": True,
            "updated_at": utc_now(),
        }
        if registration is None:
            registration = ScraperRegistration(**payload)
            await registration.insert()
        else:
            for key, value in payload.items():
                setattr(registration, key, value)
            await registration.save()

        seed.discovered_source_id = str(source.id) if source else seed.discovered_source_id
        return scraper_key


company_careers_intelligence_service = CompanyCareersIntelligenceService()
