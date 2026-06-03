from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

from beanie import PydanticObjectId
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.redis import get_redis
from app.core.time import utc_now
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.source_discovery import (
    BadDomainEntry,
    CompanySeed,
    DiscoveredSource,
    DiscoveryLLMCall,
    DiscoveryMethod,
    EmployerCareersClaim,
    ProbationOpportunity,
    ScraperRegistration,
    ScraperRegistrationStatus,
    SourceDiscoveryRun,
    SourceStatus,
)
from app.models.user import User
from app.services.opportunity_trust import apply_trust_assessment, assess_opportunity_trust

try:  # pragma: no cover - dependency availability is environment-specific
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

try:  # pragma: no cover
    import whois  # type: ignore
except Exception:  # pragma: no cover
    whois = None  # type: ignore

try:  # pragma: no cover
    from langdetect import detect  # type: ignore
except Exception:  # pragma: no cover
    detect = None  # type: ignore


logger = logging.getLogger(__name__)

QUEUE_SOURCE_QUALIFICATION = "queue:source_qualification"
QUEUE_SOURCE_EXTRACTION = "queue:source_extraction"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; VidyaVerseSourceDiscovery/1.0; "
        "+https://vidyaverse.example/discovery)"
    )
}

CAREERS_PATHS = [
    "/careers",
    "/jobs",
    "/join-us",
    "/join",
    "/work-with-us",
    "/opportunities",
    "/career",
    "/hiring",
    "/open-positions",
    "/job-openings",
]

INDIAN_CITY_TERMS = {
    "india",
    "bangalore",
    "bengaluru",
    "mumbai",
    "delhi",
    "gurgaon",
    "gurugram",
    "hyderabad",
    "pune",
    "chennai",
    "noida",
    "kolkata",
    "ahmedabad",
    "remote india",
}

LEGITIMATE_EMPLOYER_TERMS = {
    "google",
    "microsoft",
    "amazon",
    "meta",
    "apple",
    "adobe",
    "salesforce",
    "oracle",
    "ibm",
    "flipkart",
    "swiggy",
    "zomato",
    "razorpay",
    "phonepe",
    "meesho",
    "freshworks",
    "zoho",
    "infosys",
    "tcs",
    "wipro",
    "hcl",
    "tech mahindra",
    "persistent",
    "goldman",
    "morgan stanley",
    "jpmorgan",
    "deloitte",
    "ey",
    "pwc",
    "kpmg",
    "iit",
    "iisc",
    "isro",
    "drdo",
    "tifr",
}


class DiscoveryRunSummary(BaseModel):
    run_id: str
    status: str
    urls_discovered: int = 0
    urls_already_known: int = 0
    urls_queued_for_qualification: int = 0
    errors: list[str] = Field(default_factory=list)


class DiscoveryCandidate(BaseModel):
    url: str
    method: DiscoveryMethod
    discovery_query: Optional[str] = None
    name: Optional[str] = None
    source_type: Optional[str] = None
    discovered_by: Optional[str] = None


class QualificationCheckResult(BaseModel):
    score: float = Field(ge=0, le=100)
    passed: bool
    notes: str = ""
    hard_reject: bool = False


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    text: str
    elapsed_seconds: float


@dataclass
class ExtractionOutcome:
    method: str
    opportunities: list[dict[str, Any]]
    confidence: float
    parser_template: dict[str, Any]
    model_version: Optional[str] = None
    notes: str = ""


@dataclass
class ScraperRunResult:
    items: list[dict[str, Any]]
    items_parsed: int
    parse_success_rate: float
    errors: list[str] = field(default_factory=list)


def normalize_domain(value: str) -> str:
    candidate = str(value or "").strip().lower()
    if "://" in candidate:
        candidate = urlparse(candidate).netloc
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate.strip(".")


def normalize_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("url is required")
    if not re.match(r"^https?://", candidate, flags=re.I):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be absolute HTTP(S)")
    host = normalize_domain(parsed.netloc)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = []
    for key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in {"fbclid", "gclid", "msclkid", "ref", "source"}:
            continue
        for item in values:
            query_pairs.append((key, item))
    query = "&".join(f"{quote(str(k))}={quote(str(v))}" for k, v in query_pairs)
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def source_key_from_domain(domain: str, source_type: str | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", normalize_domain(domain).split(":")[0]).strip("_")
    suffix = re.sub(r"[^a-z0-9]+", "_", str(source_type or "source").lower()).strip("_")
    return f"{base}_{suffix}"[:80].strip("_") or f"source_{secrets.token_hex(4)}"


def infer_source_type(url: str, html_title: str | None = None, text: str | None = None) -> str:
    parsed = urlparse(url)
    haystack = " ".join([parsed.netloc, parsed.path, html_title or "", text or ""]).lower()
    domain = normalize_domain(parsed.netloc)
    if "hackathon" in haystack:
        return "hackathon_platform"
    if "scholarship" in haystack:
        return "scholarship_portal"
    if "research" in haystack and (domain.endswith(".edu") or domain.endswith(".ac.in") or "institute" in haystack):
        return "research_portal"
    if domain.endswith(".edu") or domain.endswith(".ac.in"):
        return "university_portal"
    if "/careers" in parsed.path.lower() or "/jobs" in parsed.path.lower() or "career" in haystack:
        if any(term in haystack for term in ["multiple companies", "companies hiring", "job board"]):
            return "job_board"
        return "company_careers"
    return "job_board"


def _object_id(value: Any) -> PydanticObjectId:
    if isinstance(value, PydanticObjectId):
        return value
    return PydanticObjectId(str(value))


def _start_of_utc_day(value: datetime | None = None) -> datetime:
    now = value or utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_utc_month(value: datetime | None = None) -> datetime:
    now = value or utc_now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class RedisQueue:
    async def push(self, queue_name: str, value: str) -> bool:
        client = get_redis()
        if client is None:
            return False
        await client.lpush(queue_name, str(value))
        return True

    async def pop_batch(self, queue_name: str, max_items: int) -> list[str]:
        client = get_redis()
        if client is None:
            return []
        items: list[str] = []
        for _ in range(max(1, int(max_items))):
            raw = await client.rpop(queue_name)
            if raw is None:
                break
            if isinstance(raw, bytes):
                items.append(raw.decode("utf-8"))
            else:
                items.append(str(raw))
        return items

    async def set_once(self, key: str, ttl_seconds: int) -> bool:
        client = get_redis()
        if client is None:
            return True
        result = await client.set(key, "1", ex=int(ttl_seconds), nx=True)
        return bool(result)

    async def increment_daily(self, key: str, ttl_seconds: int = 60 * 60 * 24) -> int:
        client = get_redis()
        if client is None:
            return 0
        value = await client.incr(key)
        if int(value) == 1:
            await client.expire(key, int(ttl_seconds))
        return int(value)


class LocalMemoryQueue(RedisQueue):
    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}
        self.keys: set[str] = set()
        self.counts: dict[str, int] = {}

    async def push(self, queue_name: str, value: str) -> bool:
        self.items.setdefault(queue_name, []).insert(0, str(value))
        return True

    async def pop_batch(self, queue_name: str, max_items: int) -> list[str]:
        rows = self.items.setdefault(queue_name, [])
        popped: list[str] = []
        for _ in range(max(1, int(max_items))):
            if not rows:
                break
            popped.append(rows.pop())
        return popped

    async def set_once(self, key: str, ttl_seconds: int) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def increment_daily(self, key: str, ttl_seconds: int = 60 * 60 * 24) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


class SourceHttpClient:
    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or float(getattr(settings, "SCRAPER_TIMEOUT_SECONDS", 20))
        self._global_semaphore = asyncio.Semaphore(
            max(1, int(getattr(settings, "SOURCE_DISCOVERY_MAX_CONCURRENT", 5)))
        )
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._last_domain_request: dict[str, float] = {}

    async def fetch(self, url: str, *, timeout_seconds: float | None = None) -> FetchedPage:
        if httpx is None:
            raise RuntimeError("httpx is required for source discovery HTTP fetches")
        normalized = normalize_url(url)
        domain = normalize_domain(urlparse(normalized).netloc)
        lock = self._domain_locks.setdefault(domain, asyncio.Lock())
        async with self._global_semaphore:
            async with lock:
                min_gap = 1.0 / max(0.1, float(getattr(settings, "SOURCE_FETCH_RATE_LIMIT", 1)))
                loop = asyncio.get_running_loop()
                now = loop.time()
                last = self._last_domain_request.get(domain, 0.0)
                if now - last < min_gap:
                    await asyncio.sleep(min_gap - (now - last))
                started = loop.time()
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=timeout_seconds or self.timeout_seconds,
                    headers=DEFAULT_HEADERS,
                    max_redirects=3,
                ) as client:
                    response = await client.get(normalized)
                self._last_domain_request[domain] = loop.time()
                return FetchedPage(
                    url=normalized,
                    final_url=str(response.url),
                    status_code=int(response.status_code),
                    text=response.text or "",
                    elapsed_seconds=max(0.0, loop.time() - started),
                )


class SearchQueryGenerator:
    templates = [
        "internship opportunities India 2026 site:careers.*",
        "apply for internship {domain} India",
        "student internship program India {company_type}",
        "{city} startup internship apply",
        "fresher jobs {tech_stack} India 2026",
        "campus recruitment portal India {domain}",
        "hackathon India students 2026 {domain}",
        "research internship India {domain}",
        "graduate engineer trainee India {company_type}",
        "software engineering internship {city} careers",
        "data science internship India apply {city}",
        "product management internship India {company_type}",
        "design internship India careers {city}",
        "finance analyst internship India students",
        "consulting internship India campus",
        "marketing internship India startup apply",
        "student fellowship India application",
        "summer internship India university students",
        "early careers India {company_type}",
        "new grad software engineer India careers",
        "off campus hiring India fresher {domain}",
        "internship program India remote students",
        "open roles interns India {tech_stack}",
        "research assistant internship India institute",
    ]
    domains = [
        "software engineering",
        "data science",
        "product management",
        "design",
        "finance",
        "consulting",
        "marketing",
        "research",
    ]
    cities = ["Bangalore", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai"]
    company_types = ["startup", "unicorn", "MNC", "FAANG", "edtech", "fintech", "healthtech"]
    tech_stacks = ["python", "machine learning", "frontend", "backend", "cloud", "cybersecurity"]

    def __init__(self, queue: RedisQueue | None = None) -> None:
        self.queue = queue or RedisQueue()

    async def generate(self, limit: int = 10) -> list[str]:
        queries: list[str] = []
        for index, template in enumerate(self.templates * 4):
            query = template.format(
                domain=self.domains[index % len(self.domains)],
                city=self.cities[index % len(self.cities)],
                company_type=self.company_types[index % len(self.company_types)],
                tech_stack=self.tech_stacks[index % len(self.tech_stacks)],
            )
            digest = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
            if await self.queue.set_once(f"source_discovery:query:{digest}", ttl_seconds=7 * 24 * 60 * 60):
                queries.append(query)
            if len(queries) >= limit:
                break
        return queries


class CareersPageFinder:
    def __init__(self, http_client: SourceHttpClient | None = None) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=10)

    async def find(self, domain: str) -> Optional[str]:
        clean_domain = normalize_domain(domain)
        base_url = f"https://{clean_domain}"
        for path in CAREERS_PATHS:
            url = f"{base_url}{path}"
            try:
                page = await self.http_client.fetch(url, timeout_seconds=6)
                if 200 <= page.status_code < 300:
                    return normalize_url(page.final_url)
            except Exception:
                continue

        try:
            page = await self.http_client.fetch(base_url, timeout_seconds=8)
            if page.status_code < 400:
                soup = BeautifulSoup(page.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    label = " ".join([link.get_text(" ", strip=True), str(link.get("href") or "")]).lower()
                    if any(term in label for term in ["career", "job", "hiring", "work with us", "join us"]):
                        return normalize_url(urljoin(page.final_url, str(link["href"])))
        except Exception:
            pass

        return await self._search_for_careers_page(clean_domain)

    async def _search_for_careers_page(self, domain: str) -> Optional[str]:
        key = (getattr(settings, "SERPAPI_KEY", "") or "").strip()
        if not key or httpx is None:
            return None
        params = {
            "engine": "google",
            "q": f"site:{domain} careers OR jobs internship",
            "api_key": key,
            "num": "5",
        }
        async with httpx.AsyncClient(timeout=10, headers=DEFAULT_HEADERS) as client:
            response = await client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            payload = response.json()
        for row in payload.get("organic_results", []) or []:
            link = str(row.get("link") or "")
            if domain in normalize_domain(urlparse(link).netloc):
                return normalize_url(link)
        return None


class SourceDiscoveryEngine:
    def __init__(
        self,
        *,
        http_client: SourceHttpClient | None = None,
        queue: RedisQueue | None = None,
    ) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=10)
        self.queue = queue or RedisQueue()
        self.query_generator = SearchQueryGenerator(queue=self.queue)
        self.careers_finder = CareersPageFinder(http_client=self.http_client)

    async def run_discovery(self, *, triggered_by: str = "scheduler") -> DiscoveryRunSummary:
        run = SourceDiscoveryRun(run_id=str(uuid.uuid4()), triggered_by=triggered_by)
        await run.insert()
        if not bool(getattr(settings, "DISCOVERY_ENABLED", True)):
            run.status = "completed"
            run.finished_at = utc_now()
            await run.save()
            return DiscoveryRunSummary(run_id=run.run_id, status="disabled")

        try:
            results = await asyncio.gather(
                self._discover_from_web_search(run),
                self._discover_from_company_seeds(),
                self._discover_from_similar_sources(),
                return_exceptions=True,
            )
            candidates: list[DiscoveryCandidate] = []
            for result in results:
                if isinstance(result, Exception):
                    run.errors.append(str(result))
                    continue
                candidates.extend(result)

            queued = 0
            already_known = 0
            for candidate in candidates:
                outcome = await self._insert_discovered_source(candidate)
                if outcome == "queued":
                    queued += 1
                elif outcome == "known":
                    already_known += 1

            run.urls_discovered = len(candidates)
            run.urls_already_known = already_known
            run.urls_queued_for_qualification = queued
            run.status = "completed"
        except Exception as exc:
            run.status = "failed"
            run.errors.append(str(exc))
        finally:
            run.finished_at = utc_now()
            await run.save()

        return DiscoveryRunSummary(
            run_id=run.run_id,
            status=run.status,
            urls_discovered=run.urls_discovered,
            urls_already_known=run.urls_already_known,
            urls_queued_for_qualification=run.urls_queued_for_qualification,
            errors=list(run.errors or []),
        )

    async def _discover_from_web_search(self, run: SourceDiscoveryRun) -> list[DiscoveryCandidate]:
        key = (getattr(settings, "SERPAPI_KEY", "") or "").strip()
        if not key or httpx is None:
            return []
        queries = await self.query_generator.generate(limit=10)
        candidates: list[DiscoveryCandidate] = []
        async with httpx.AsyncClient(timeout=10, headers=DEFAULT_HEADERS) as client:
            for query in queries:
                params = {"engine": "google", "q": query, "api_key": key, "num": "5"}
                try:
                    response = await client.get("https://serpapi.com/search.json", params=params)
                    response.raise_for_status()
                    payload = response.json()
                    run.queries_executed += 1
                    for row in payload.get("organic_results", [])[:5]:
                        link = str(row.get("link") or "")
                        if link:
                            candidates.append(
                                DiscoveryCandidate(
                                    url=link,
                                    method=DiscoveryMethod.web_search,
                                    discovery_query=query,
                                    name=str(row.get("title") or "") or None,
                                )
                            )
                except Exception as exc:
                    run.errors.append(f"web_search:{query}:{exc}")
        return candidates

    async def _discover_from_company_seeds(self, limit: int = 50) -> list[DiscoveryCandidate]:
        seeds = await self.next_company_seeds(limit=limit)
        candidates: list[DiscoveryCandidate] = []
        for seed in seeds:
            careers_url = seed.careers_url
            if not careers_url:
                careers_url = await self.careers_finder.find(seed.domain)
                seed.last_checked_at = utc_now()
                if careers_url:
                    seed.careers_url = careers_url
                seed.updated_at = utc_now()
                await seed.save()
            if careers_url:
                candidates.append(
                    DiscoveryCandidate(
                        url=careers_url,
                        method=DiscoveryMethod.company_seed,
                        discovery_query=seed.company_name,
                        name=seed.company_name,
                        source_type="company_careers",
                    )
                )
        return candidates

    async def _discover_from_similar_sources(self) -> list[DiscoveryCandidate]:
        promoted = await DiscoveredSource.find_many(
            {
                "status": SourceStatus.promoted.value,
                "trust_score": {"$gt": 80},
            }
        ).limit(25).to_list()
        candidates: list[DiscoveryCandidate] = []
        for source in promoted:
            try:
                page = await self.http_client.fetch(source.url, timeout_seconds=8)
                soup = BeautifulSoup(page.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    label = " ".join([link.get_text(" ", strip=True), str(link.get("href") or "")]).lower()
                    if not any(term in label for term in ["careers", "jobs", "internship", "hiring"]):
                        continue
                    url = normalize_url(urljoin(page.final_url, str(link["href"])))
                    if normalize_domain(urlparse(url).netloc) != source.domain:
                        candidates.append(
                            DiscoveryCandidate(
                                url=url,
                                method=DiscoveryMethod.similar_source_expansion,
                                discovery_query=source.domain,
                            )
                        )
            except Exception:
                continue
        return candidates

    async def next_company_seeds(self, *, limit: int = 50) -> list[CompanySeed]:
        rows = await CompanySeed.find_many(
            CompanySeed.india_presence == True,  # noqa: E712
            CompanySeed.student_friendly == True,  # noqa: E712
        ).to_list()
        rows.sort(
            key=lambda row: (
                0 if row.careers_url else 1,
                0 if str(row.company_size).lower() == "startup" else 1,
                row.last_checked_at or datetime.min.replace(tzinfo=utc_now().tzinfo),
                row.company_name.lower(),
            )
        )
        return rows[: max(1, int(limit))]

    async def enqueue_known_seed_sources(self, *, limit: int = 50) -> dict[str, Any]:
        candidates = await self._discover_from_company_seeds(limit=limit)
        queued = 0
        known = 0
        for candidate in candidates:
            outcome = await self._insert_discovered_source(candidate)
            if outcome == "queued":
                queued += 1
            elif outcome == "known":
                known += 1
        return {"processed": len(candidates), "queued": queued, "already_known": known}

    async def submit_user_source(self, *, url: str, user: User, context: str | None = None) -> DiscoveredSource:
        candidate = DiscoveryCandidate(
            url=url,
            method=DiscoveryMethod.user_submission,
            discovery_query=(context or "")[:300] or None,
            discovered_by=str(user.id),
        )
        normalized = normalize_url(candidate.url)
        domain = normalize_domain(urlparse(normalized).netloc)
        bad = await BadDomainEntry.find_one(BadDomainEntry.domain == domain)
        if bad is not None:
            raise ValueError("domain_is_blocked")
        existing = await DiscoveredSource.find_one(DiscoveredSource.domain == domain)
        if existing is not None:
            return existing

        daily_limit = int(getattr(settings, "SOURCE_SUBMISSION_DAILY_LIMIT", 3))
        rate_key = f"source_submission:{str(user.id)}:{utc_now().date().isoformat()}"
        count = await self.queue.increment_daily(rate_key)
        if count and count > daily_limit:
            raise ValueError("daily_submission_limit_exceeded")
        if count == 0:
            today_count = await DiscoveredSource.find_many(
                DiscoveredSource.discovery_method == DiscoveryMethod.user_submission,
                DiscoveredSource.discovered_by == str(user.id),
                DiscoveredSource.discovered_at >= _start_of_utc_day(),
            ).count()
            if today_count >= daily_limit:
                raise ValueError("daily_submission_limit_exceeded")
        source = DiscoveredSource(
            url=normalized,
            domain=domain,
            discovery_method=DiscoveryMethod.user_submission,
            discovery_query=candidate.discovery_query,
            discovered_by=str(user.id),
            requires_admin_review=True,
            admin_notes=context,
        )
        await source.insert()
        await self.queue.push(QUEUE_SOURCE_QUALIFICATION, str(source.id))
        return source

    async def bulk_import_sources(
        self,
        *,
        csv_text: str,
        actor: User,
    ) -> dict[str, Any]:
        imported = 0
        skipped_duplicates = 0
        invalid_urls: list[str] = []
        reader = csv.DictReader(StringIO(csv_text))
        for row in reader:
            raw_url = str(row.get("url") or "").strip()
            if not raw_url:
                continue
            try:
                candidate = DiscoveryCandidate(
                    url=raw_url,
                    method=DiscoveryMethod.admin_manual,
                    name=str(row.get("name") or "").strip() or None,
                    source_type=str(row.get("source_type") or "").strip() or None,
                    discovery_query=str(row.get("notes") or "").strip() or None,
                    discovered_by=str(actor.id),
                )
                outcome = await self._insert_discovered_source(candidate)
                if outcome == "queued":
                    imported += 1
                elif outcome == "known":
                    skipped_duplicates += 1
            except Exception:
                invalid_urls.append(raw_url)
        return {
            "imported": imported,
            "skipped_duplicates": skipped_duplicates,
            "invalid_urls": invalid_urls,
        }

    async def _insert_discovered_source(self, candidate: DiscoveryCandidate) -> str:
        try:
            normalized = normalize_url(candidate.url)
        except ValueError:
            return "invalid"
        domain = normalize_domain(urlparse(normalized).netloc)
        if await BadDomainEntry.find_one(BadDomainEntry.domain == domain):
            return "blocked"
        if await DiscoveredSource.find_one(DiscoveredSource.domain == domain):
            return "known"
        if await ScraperRegistration.find_one(ScraperRegistration.domain == domain):
            return "known"
        if await self._robots_disallows(normalized):
            try:
                await BadDomainEntry(domain=domain, reason="blocked_by_robots", added_by="system").insert()
            except DuplicateKeyError:
                pass
            return "blocked"
        source = DiscoveredSource(
            url=normalized,
            domain=domain,
            name=candidate.name,
            source_type=candidate.source_type or infer_source_type(normalized),
            discovery_method=candidate.method,
            discovery_query=candidate.discovery_query,
            discovered_by=candidate.discovered_by or "system",
            requires_admin_review=candidate.method == DiscoveryMethod.user_submission,
        )
        try:
            await source.insert()
        except DuplicateKeyError:
            return "known"
        if candidate.method == DiscoveryMethod.company_seed:
            seed = await CompanySeed.find_one(CompanySeed.domain == domain)
            if seed is None and candidate.discovery_query:
                seed = await CompanySeed.find_one(CompanySeed.company_name == candidate.discovery_query)
            if seed is not None:
                seed.discovered_source_id = str(source.id)
                seed.updated_at = utc_now()
                await seed.save()
        await self.queue.push(QUEUE_SOURCE_QUALIFICATION, str(source.id))
        return "queued"

    async def _robots_disallows(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            page = await self.http_client.fetch(robots_url, timeout_seconds=4)
        except Exception:
            return False
        if page.status_code >= 400:
            return False
        path = parsed.path or "/"
        active_for_all = False
        for line in page.text.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            if stripped.lower().startswith("user-agent:"):
                active_for_all = stripped.split(":", 1)[1].strip() == "*"
            elif active_for_all and stripped.lower().startswith("disallow:"):
                rule = stripped.split(":", 1)[1].strip()
                if rule and path.startswith(rule):
                    return True
        return False


class SourceQualificationService:
    weights = {
        "reachability": 15,
        "https": 5,
        "domain_age": 10,
        "content_language": 10,
        "opportunity_density": 25,
        "spam_signals": 20,
        "structured_data_quality": 15,
    }

    def __init__(self, http_client: SourceHttpClient | None = None, queue: RedisQueue | None = None) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=8)
        self.queue = queue or RedisQueue()

    async def qualify_source(self, source_id: str | PydanticObjectId) -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        source.status = SourceStatus.qualifying
        source.updated_at = utc_now()
        await source.save()

        page: FetchedPage | None = None
        details: dict[str, Any] = {}
        try:
            page = await self.http_client.fetch(source.url, timeout_seconds=5)
            details["reachability"] = self._reachability_check(page).model_dump()
        except Exception as exc:
            details["reachability"] = QualificationCheckResult(
                score=0,
                passed=False,
                notes=str(exc),
                hard_reject=True,
            ).model_dump()

        html = page.text if page else ""
        details["https"] = self._https_check(source.url).model_dump()
        details["domain_age"] = (await self._domain_age_check(source.domain)).model_dump()
        details["content_language"] = self._content_language_check(html).model_dump()
        details["opportunity_density"] = self._opportunity_density_check(html).model_dump()
        details["spam_signals"] = self._spam_signals_check(source.domain, html).model_dump()
        details["structured_data_quality"] = self._structured_data_quality_check(html).model_dump()

        hard_rejects = [
            name
            for name, detail in details.items()
            if bool(detail.get("hard_reject")) or (name in {"reachability", "spam_signals"} and not detail.get("passed"))
        ]
        weighted_total = sum(float(details[name]["score"]) * weight for name, weight in self.weights.items())
        max_total = sum(self.weights.values())
        score = round(weighted_total / max_total, 2)

        source.qualification_score = score
        source.qualification_details = details
        source.source_type = infer_source_type(source.url, self._title_from_html(html), BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:500] if html else "")
        if hard_rejects:
            source.status = SourceStatus.rejected
            source.rejection_reason = hard_rejects[0]
            source.rejected_at = utc_now()
        elif score >= float(getattr(settings, "QUALIFICATION_MIN_SCORE", 60)):
            source.status = SourceStatus.qualified
            source.qualified_at = utc_now()
            await self.queue.push(QUEUE_SOURCE_EXTRACTION, str(source.id))
        else:
            source.status = SourceStatus.rejected
            source.rejection_reason = f"low_qualification_score:{score}"
            source.rejected_at = utc_now()
        source.updated_at = utc_now()
        await source.save()
        return source

    def _reachability_check(self, page: FetchedPage) -> QualificationCheckResult:
        reachable = 200 <= page.status_code < 300 and page.elapsed_seconds < 5
        return QualificationCheckResult(
            score=100 if reachable else 0,
            passed=reachable,
            notes=f"status={page.status_code},elapsed={page.elapsed_seconds:.2f}s",
            hard_reject=not reachable,
        )

    def _https_check(self, url: str) -> QualificationCheckResult:
        https = urlparse(url).scheme.lower() == "https"
        return QualificationCheckResult(score=100 if https else 30, passed=True, notes="https" if https else "http")

    async def _domain_age_check(self, domain: str) -> QualificationCheckResult:
        if whois is None:
            return QualificationCheckResult(score=50, passed=True, notes="whois_unavailable")
        try:
            data = await asyncio.to_thread(whois.whois, domain)
            created = getattr(data, "creation_date", None) or data.get("creation_date")
            if isinstance(created, list):
                created = next((item for item in created if item), None)
            if not isinstance(created, datetime):
                return QualificationCheckResult(score=50, passed=True, notes="domain_age_unknown")
            age_days = (utc_now().replace(tzinfo=None) - created.replace(tzinfo=None)).days
            if age_days >= 365 * 3:
                score = 100
            elif age_days >= 365:
                score = 70
            elif age_days >= 180:
                score = 40
            else:
                score = 0
            return QualificationCheckResult(score=score, passed=True, notes=f"age_days={age_days}")
        except Exception as exc:
            return QualificationCheckResult(score=50, passed=True, notes=f"domain_age_error:{exc}")

    def _content_language_check(self, html: str) -> QualificationCheckResult:
        text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)[:2000]
        if not text:
            return QualificationCheckResult(score=0, passed=False, notes="empty_page")
        if detect is None:
            indian_hint = any(term in text.lower() for term in INDIAN_CITY_TERMS)
            return QualificationCheckResult(score=80 if indian_hint else 70, passed=True, notes="langdetect_unavailable")
        try:
            language = detect(text)
            if language == "en":
                return QualificationCheckResult(score=100, passed=True, notes="english")
            if language in {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "ur"}:
                return QualificationCheckResult(score=50, passed=True, notes=f"regional:{language}")
            return QualificationCheckResult(score=0, passed=False, notes=f"language:{language}")
        except Exception:
            return QualificationCheckResult(score=50, passed=True, notes="language_unknown")

    def _opportunity_density_check(self, html: str) -> QualificationCheckResult:
        soup = BeautifulSoup(html or "", "html.parser")
        schema_jobs = self._schema_jobpostings(soup)
        if schema_jobs:
            return QualificationCheckResult(score=90, passed=True, notes=f"schema_jobpostings={len(schema_jobs)}")
        selectors = [
            "[class*=job]",
            "[class*=career]",
            "[class*=opening]",
            "[data-job-id]",
            "[data-testid*=job]",
            "li",
            "article",
        ]
        candidate_count = 0
        for selector in selectors:
            for element in soup.select(selector)[:100]:
                text = element.get_text(" ", strip=True).lower()
                if len(text) < 20:
                    continue
                if any(term in text for term in ["apply", "intern", "job", "role", "opening", "hiring"]):
                    candidate_count += 1
            if candidate_count >= 10:
                break
        if candidate_count >= 10:
            score = 100
        elif candidate_count >= 5:
            score = 80
        elif candidate_count >= 2:
            score = 50
        elif candidate_count >= 1:
            score = 20
        else:
            score = 0
        return QualificationCheckResult(score=score, passed=score > 0, notes=f"candidate_items={candidate_count}")

    def _spam_signals_check(self, domain: str, html: str) -> QualificationCheckResult:
        lower_domain = normalize_domain(domain)
        if any(lower_domain.endswith(tld) for tld in [".xyz", ".tk", ".ml", ".ga", ".cf"]):
            return QualificationCheckResult(score=0, passed=False, hard_reject=True, notes="bad_tld")
        text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True).lower()
        spam_phrases = [
            "earn money from home",
            "no experience needed earn",
            "mlm",
            "referral income",
            "work from home earn daily",
            "registration fee",
            "pay to apply",
        ]
        for phrase in spam_phrases:
            if phrase in text:
                return QualificationCheckResult(score=0, passed=False, hard_reject=True, notes=f"spam_phrase:{phrase}")
        redirect_scripts = len(re.findall(r"location\.(href|replace)|window\.open|meta http-equiv=.refresh", html or "", flags=re.I))
        if redirect_scripts > 3:
            return QualificationCheckResult(score=0, passed=False, hard_reject=True, notes="excessive_redirect_scripts")
        ad_units = len(re.findall(r"adsense|ad-banner|ad_slot|doubleclick|googlesyndication", html or "", flags=re.I))
        if ad_units > 5:
            return QualificationCheckResult(score=40, passed=True, notes=f"many_ads={ad_units}")
        return QualificationCheckResult(score=100, passed=True, notes="clean")

    def _structured_data_quality_check(self, html: str) -> QualificationCheckResult:
        soup = BeautifulSoup(html or "", "html.parser")
        if self._schema_jobpostings(soup):
            return QualificationCheckResult(score=100, passed=True, notes="schema_org_jobposting")
        if soup.select("[class*=job] [href], [class*=opening] [href], article a[href]"):
            return QualificationCheckResult(score=70, passed=True, notes="clear_html_patterns")
        text = soup.get_text(" ", strip=True)
        if len(text) < 200 and len(soup.find_all("script")) > 5:
            return QualificationCheckResult(score=0, passed=False, notes="spa_no_ssr_content")
        return QualificationCheckResult(score=40, passed=True, notes="unstructured")

    def _schema_jobpostings(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text() or ""
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            rows.extend(_extract_jobposting_objects(payload))
        return rows

    def _title_from_html(self, html: str) -> str | None:
        if not html:
            return None
        title = BeautifulSoup(html, "html.parser").find("title")
        return title.get_text(" ", strip=True) if title else None

    async def process_batch(self, *, max_items: int = 50) -> dict[str, Any]:
        ids = await self.queue.pop_batch(QUEUE_SOURCE_QUALIFICATION, max_items=max_items)
        if not ids:
            fallback_rows = await DiscoveredSource.find_many(
                DiscoveredSource.status == SourceStatus.discovered,
            ).sort("discovered_at").limit(max(1, int(max_items))).to_list()
            ids = [str(row.id) for row in fallback_rows if row.id is not None]
        processed = 0
        qualified = 0
        rejected = 0
        errors: list[str] = []
        for source_id in ids:
            try:
                source = await self.qualify_source(source_id)
                processed += 1
                if source.status == SourceStatus.qualified:
                    qualified += 1
                elif source.status == SourceStatus.rejected:
                    rejected += 1
            except Exception as exc:
                errors.append(f"{source_id}:{exc}")
        return {"processed": processed, "qualified": qualified, "rejected": rejected, "errors": errors}


def _extract_jobposting_objects(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            rows.extend(_extract_jobposting_objects(item))
    elif isinstance(payload, dict):
        item_type = payload.get("@type")
        item_types = {str(item).lower() for item in item_type} if isinstance(item_type, list) else {str(item_type).lower()}
        if "jobposting" in item_types:
            rows.append(payload)
        graph = payload.get("@graph")
        if graph:
            rows.extend(_extract_jobposting_objects(graph))
    return rows


class AdaptiveExtractionService:
    def __init__(self, http_client: SourceHttpClient | None = None, queue: RedisQueue | None = None) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=10)
        self.queue = queue or RedisQueue()

    async def extract_source(self, source_id: str | PydanticObjectId) -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        source.status = SourceStatus.extracting
        source.updated_at = utc_now()
        await source.save()

        try:
            page = await self.http_client.fetch(source.url, timeout_seconds=10)
            outcome = await self._extract_from_page(source, page)
            valid = [self._normalize_opportunity(row, source.url) for row in outcome.opportunities]
            valid = [row for row in valid if row]
            confidence = self._overall_confidence(outcome.confidence, valid)
            source.extraction_confidence = confidence
            source.parser_template = outcome.parser_template
            source.sample_opportunities = valid[:3]
            source.extraction_model_version = outcome.model_version
            source.extracted_at = utc_now()
            if confidence >= 0.7 and len(valid) >= 2:
                source.status = SourceStatus.probation
                source.probation_start = utc_now()
            else:
                source.status = SourceStatus.rejected
                source.rejection_reason = f"low_extraction_confidence:{confidence:.2f}"
                source.rejected_at = utc_now()
                if 0.4 <= confidence < 0.7:
                    source.requires_admin_review = True
        except Exception as exc:
            source.status = SourceStatus.rejected
            source.rejection_reason = f"extraction_error:{exc}"
            source.rejected_at = utc_now()
        source.updated_at = utc_now()
        await source.save()
        if source.status == SourceStatus.probation and source.trust_score is None:
            source = await TrustScoringEngine().score_source(source.id)
        return source

    async def _extract_from_page(self, source: DiscoveredSource, page: FetchedPage) -> ExtractionOutcome:
        soup = BeautifulSoup(page.text or "", "html.parser")
        schema_rows = _extract_jobposting_objects(
            [
                _safe_json_loads(script.string or script.get_text() or "")
                for script in soup.find_all("script", attrs={"type": "application/ld+json"})
            ]
        )
        if schema_rows:
            opportunities = [self._map_schema_job(row, page.final_url) for row in schema_rows[:10]]
            return ExtractionOutcome(
                method="schema_org",
                opportunities=opportunities,
                confidence=0.9,
                parser_template=self._build_parser_template("schema_org", source, page.final_url),
            )
        ats = self._detect_ats(page.final_url, page.text)
        if ats:
            opportunities = await self._extract_ats(ats, source, page.final_url)
            return ExtractionOutcome(
                method=ats["method"],
                opportunities=opportunities,
                confidence=0.92 if opportunities else 0.55,
                parser_template=self._build_parser_template(ats["method"], source, page.final_url, ats),
            )

        heuristic = self._extract_with_heuristics(soup, page.final_url, source)
        if len(heuristic) >= 2:
            return ExtractionOutcome(
                method="heuristic_css",
                opportunities=heuristic,
                confidence=0.72,
                parser_template=self._build_parser_template("llm_css", source, page.final_url),
            )
        return await self._extract_with_llm(source, page)

    def _map_schema_job(self, row: dict[str, Any], base_url: str) -> dict[str, Any]:
        organization = row.get("hiringOrganization") or {}
        location = row.get("jobLocation") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        address = location.get("address") if isinstance(location, dict) else {}
        return {
            "title": row.get("title"),
            "company": organization.get("name") if isinstance(organization, dict) else None,
            "location": _join_non_empty(
                [
                    address.get("addressLocality") if isinstance(address, dict) else None,
                    address.get("addressRegion") if isinstance(address, dict) else None,
                    address.get("addressCountry") if isinstance(address, dict) else None,
                ]
            ),
            "work_mode": "remote" if row.get("jobLocationType") == "TELECOMMUTE" else None,
            "apply_url": urljoin(base_url, str(row.get("url") or row.get("sameAs") or base_url)),
            "description_preview": BeautifulSoup(str(row.get("description") or ""), "html.parser").get_text(" ", strip=True)[:200],
            "tags": [],
            "opportunity_type": "internship" if "intern" in str(row.get("title") or "").lower() else "job",
            "posted_date_text": row.get("datePosted"),
            "deadline_text": row.get("validThrough"),
        }

    def _detect_ats(self, url: str, html: str) -> Optional[dict[str, str]]:
        haystack = f"{url}\n{html}".lower()
        patterns = [
            ("ats_greenhouse", r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([a-z0-9_-]+)"),
            ("ats_lever", r"jobs\.lever\.co/([a-z0-9_-]+)"),
            ("ats_ashby", r"jobs\.ashbyhq\.com/([a-z0-9_-]+)"),
            ("ats_workday", r"myworkdayjobs\.com/([^/\"']+)"),
        ]
        for method, pattern in patterns:
            match = re.search(pattern, haystack)
            if match:
                return {"method": method, "slug": match.group(1)}
        return None

    async def _extract_ats(self, ats: dict[str, str], source: DiscoveredSource, base_url: str) -> list[dict[str, Any]]:
        method = ats["method"]
        slug = ats["slug"]
        if method == "ats_greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            page = await self.http_client.fetch(url, timeout_seconds=10)
            payload = json.loads(page.text)
            return [
                {
                    "title": row.get("title"),
                    "company": source.name,
                    "location": (row.get("location") or {}).get("name"),
                    "apply_url": row.get("absolute_url"),
                    "description_preview": BeautifulSoup(str(row.get("content") or ""), "html.parser").get_text(" ", strip=True)[:200],
                    "tags": [dept.get("name") for dept in row.get("departments", []) if dept.get("name")],
                    "opportunity_type": "internship" if "intern" in str(row.get("title") or "").lower() else "job",
                    "posted_date_text": row.get("updated_at"),
                }
                for row in (payload.get("jobs") or [])[:20]
            ]
        if method == "ats_lever":
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            page = await self.http_client.fetch(url, timeout_seconds=10)
            payload = json.loads(page.text)
            return [
                {
                    "title": row.get("text"),
                    "company": source.name,
                    "location": row.get("categories", {}).get("location"),
                    "work_mode": row.get("workplaceType"),
                    "apply_url": row.get("hostedUrl"),
                    "description_preview": BeautifulSoup(str(row.get("descriptionPlain") or row.get("description") or ""), "html.parser").get_text(" ", strip=True)[:200],
                    "tags": [row.get("categories", {}).get("team"), row.get("categories", {}).get("commitment")],
                    "opportunity_type": "internship" if "intern" in str(row.get("text") or "").lower() else "job",
                    "posted_date_text": row.get("createdAt"),
                }
                for row in payload[:20]
            ]
        if method == "ats_ashby":
            url = f"https://api.ashbyhq.com/posting-public/jobs?organizationHostedJobsPageName={slug}"
            page = await self.http_client.fetch(url, timeout_seconds=10)
            payload = json.loads(page.text)
            jobs = payload.get("jobs") if isinstance(payload, dict) else []
            return [
                {
                    "title": row.get("title"),
                    "company": source.name,
                    "location": row.get("locationName"),
                    "apply_url": row.get("jobUrl") or urljoin(base_url, str(row.get("id") or "")),
                    "description_preview": BeautifulSoup(str(row.get("descriptionHtml") or ""), "html.parser").get_text(" ", strip=True)[:200],
                    "tags": row.get("departmentName") and [row.get("departmentName")] or [],
                    "opportunity_type": "internship" if "intern" in str(row.get("title") or "").lower() else "job",
                }
                for row in jobs[:20]
            ]
        return []

    def _extract_with_heuristics(self, soup: BeautifulSoup, base_url: str, source: DiscoveredSource) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        selectors = ["[data-job-id]", "[class*=job]", "[class*=opening]", "article", "li"]
        for selector in selectors:
            for element in soup.select(selector)[:30]:
                text = element.get_text(" ", strip=True)
                if len(text) < 20 or not any(term in text.lower() for term in ["apply", "intern", "job", "engineer", "analyst"]):
                    continue
                link = element.select_one("a[href]")
                title_node = element.select_one("h1,h2,h3,h4,[class*=title],[class*=role]")
                title = title_node.get_text(" ", strip=True) if title_node else text[:90]
                rows.append(
                    {
                        "title": title,
                        "company": source.name,
                        "location": _extract_location_hint(text),
                        "work_mode": _extract_work_mode_hint(text),
                        "apply_url": urljoin(base_url, str(link.get("href") if link else base_url)),
                        "description_preview": text[:200],
                        "tags": _extract_skill_tags(text),
                        "opportunity_type": "internship" if "intern" in text.lower() else "job",
                    }
                )
                if len(rows) >= 5:
                    return rows
        return rows

    async def _extract_with_llm(self, source: DiscoveredSource, page: FetchedPage) -> ExtractionOutcome:
        key = (getattr(settings, "CLAUDE_API_KEY", "") or "").strip()
        model = (getattr(settings, "CLAUDE_MODEL", "") or "claude-3-5-sonnet-20241022").strip()
        if not key or httpx is None:
            return ExtractionOutcome(method="llm_css", opportunities=[], confidence=0.0, parser_template={})
        calls_last_hour = await DiscoveryLLMCall.find_many(DiscoveryLLMCall.created_at >= utc_now() - timedelta(hours=1)).count()
        if calls_last_hour >= int(getattr(settings, "MAX_LLM_EXTRACTIONS_PER_HOUR", 10)):
            return ExtractionOutcome(method="llm_css", opportunities=[], confidence=0.0, parser_template={}, notes="llm_hourly_limit")
        month_spend = await self._llm_spend_since(_start_of_utc_month())
        monthly_budget = float(getattr(settings, "MONTHLY_LLM_BUDGET_USD", 20.0))
        if monthly_budget > 0 and month_spend >= monthly_budget:
            return ExtractionOutcome(method="llm_css", opportunities=[], confidence=0.0, parser_template={}, notes="llm_monthly_budget_exhausted")

        cleaned_html = self._clean_html_for_llm(page.text)
        system_prompt = (
            "You are a structured data extractor for an opportunity aggregation platform. "
            "Extract up to 5 opportunity listings and the reusable CSS/HTML pattern. "
            "Return only valid JSON with keys opportunities, extraction_confidence, source_type, "
            "listing_selector, pagination_pattern, notes."
        )
        payload = {
            "model": model,
            "max_tokens": 1800,
            "system": system_prompt,
            "messages": [{"role": "user", "content": f"<html>{cleaned_html}</html>"}],
        }
        success = False
        error: str | None = None
        cost = 0.0
        tokens = 0
        confidence = 0.0
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            text = "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
            parsed = _safe_json_loads(text) or _extract_json_object(text) or {}
            opportunities = list(parsed.get("opportunities") or parsed.get("listings") or [])
            confidence = float(parsed.get("extraction_confidence") or 0)
            usage = data.get("usage") or {}
            tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
            cost = tokens * 0.000003
            success = True
            template = self._build_parser_template(
                "llm_css",
                source,
                page.final_url,
                {
                    "listing_selector": parsed.get("listing_selector"),
                    "pagination_pattern": parsed.get("pagination_pattern"),
                },
            )
            return ExtractionOutcome(
                method="llm_css",
                opportunities=opportunities,
                confidence=confidence,
                parser_template=template,
                model_version=model,
                notes=str(parsed.get("notes") or ""),
            )
        except Exception as exc:
            error = str(exc)
            return ExtractionOutcome(method="llm_css", opportunities=[], confidence=0.0, parser_template={}, model_version=model, notes=error)
        finally:
            await DiscoveryLLMCall(
                domain=source.domain,
                method="llm_css",
                model=model,
                tokens_used=tokens,
                confidence=confidence,
                cost_estimate_usd=cost,
                success=success,
                error=error,
            ).insert()
            if success:
                try:
                    from app.core import metrics as metrics_module

                    if metrics_module.DISCOVERY_LLM_CALLS_TOTAL is not None:
                        metrics_module.DISCOVERY_LLM_CALLS_TOTAL.inc()
                    if metrics_module.DISCOVERY_LLM_COST_USD_TOTAL is not None:
                        metrics_module.DISCOVERY_LLM_COST_USD_TOTAL.inc(cost)
                except Exception:
                    logger.debug("Failed to update discovery LLM metrics", exc_info=True)

    async def _llm_spend_since(self, since: datetime) -> float:
        rows = await DiscoveryLLMCall.find_many(DiscoveryLLMCall.created_at >= since).to_list()
        return sum(float(row.cost_estimate_usd or 0.0) for row in rows)

    def _clean_html_for_llm(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        main = soup.select_one("main,article,[role=main]") or max(soup.find_all("div") or [soup], key=lambda node: len(node.get_text(" ", strip=True)))
        return str(main)[:8000]

    def _build_parser_template(
        self,
        method: str,
        source: DiscoveredSource,
        base_url: str,
        overrides: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        overrides = overrides or {}
        return {
            "extraction_method": method,
            "listing_selector": overrides.get("listing_selector") or "[data-job-id], .job, .opening, article, li",
            "title_selector": overrides.get("title_selector") or "h1,h2,h3,h4,[class*=title],[class*=role]",
            "company_selector": overrides.get("company_selector") or "",
            "location_selector": overrides.get("location_selector") or "[class*=location]",
            "apply_link_selector": overrides.get("apply_link_selector") or "a[href]",
            "pagination_pattern": overrides.get("pagination_pattern"),
            "max_pages": int(overrides.get("max_pages") or 10),
            "items_per_page_estimate": int(overrides.get("items_per_page_estimate") or 20),
            "requires_javascript": bool(overrides.get("requires_javascript") or False),
            "ats_slug": overrides.get("slug"),
            "careers_url": base_url,
            "last_validated_at": utc_now().isoformat(),
            "source_domain": source.domain,
        }

    def _normalize_opportunity(self, row: dict[str, Any], base_url: str) -> dict[str, Any] | None:
        title = str(row.get("title") or "").strip()
        apply_url = str(row.get("apply_url") or row.get("url") or "").strip()
        if not title or not apply_url:
            return None
        try:
            normalized_url = normalize_url(urljoin(base_url, apply_url))
        except Exception:
            return None
        row["title"] = title
        row["apply_url"] = normalized_url
        row["url"] = normalized_url
        row["description_preview"] = str(row.get("description_preview") or row.get("description") or "")[:500]
        return row

    def _overall_confidence(self, base_confidence: float, rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        completeness_scores = []
        quality_scores = []
        for row in rows:
            fields = ["title", "company", "location", "apply_url", "description_preview", "opportunity_type"]
            completeness_scores.append(sum(1 for field in fields if row.get(field)) / len(fields))
            assessment = assess_opportunity_trust(
                {
                    "title": row.get("title") or "",
                    "description": row.get("description_preview") or "",
                    "url": row.get("apply_url") or "",
                    "source": row.get("company") or "",
                    "university": row.get("company") or "Unknown",
                }
            )
            quality_scores.append(max(0.0, min(1.0, (100 - assessment.risk_score) / 100)))
        return round((float(base_confidence) + (sum(completeness_scores) / len(completeness_scores)) + (sum(quality_scores) / len(quality_scores))) / 3, 3)

    async def process_batch(self, *, max_items: int = 20) -> dict[str, Any]:
        ids = await self.queue.pop_batch(QUEUE_SOURCE_EXTRACTION, max_items=max_items)
        if not ids:
            fallback_rows = await DiscoveredSource.find_many(
                DiscoveredSource.status == SourceStatus.qualified,
            ).sort("qualified_at", "discovered_at").limit(max(1, int(max_items))).to_list()
            ids = [str(row.id) for row in fallback_rows if row.id is not None]
        processed = 0
        probation = 0
        rejected = 0
        errors: list[str] = []
        for source_id in ids:
            try:
                source = await self.extract_source(source_id)
                processed += 1
                if source.status == SourceStatus.probation:
                    probation += 1
                elif source.status == SourceStatus.rejected:
                    rejected += 1
            except Exception as exc:
                errors.append(f"{source_id}:{exc}")
        return {"processed": processed, "probation": probation, "rejected": rejected, "errors": errors}


class TrustScoringEngine:
    async def score_source(self, source_id: str | PydanticObjectId) -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        samples = list(source.sample_opportunities or [])
        extraction_quality = round(float(source.extraction_confidence or 0) * 25, 2)
        field_completeness = self._field_completeness_score(samples)
        relevance = self._relevance_score(samples)
        legitimacy = await self._legitimacy_score(source, samples)
        cross_validation = await self._cross_validation_score(samples)
        reputation = self._domain_reputation_score(source)
        total = round(
            min(
                100.0,
                extraction_quality
                + field_completeness
                + relevance
                + legitimacy
                + cross_validation
                + reputation
                + float(source.trust_score_boost or 0),
            ),
            2,
        )
        source.trust_score = total
        source.trust_breakdown = {
            "extraction_quality": {"score": extraction_quality, "max": 25, "details": "extraction confidence"},
            "field_completeness": {"score": field_completeness, "max": 20, "details": "required fields present"},
            "opportunity_relevance": {"score": relevance, "max": 20, "details": "student and India relevance"},
            "source_legitimacy": {"score": legitimacy, "max": 15, "details": "known employer/source signals"},
            "cross_source_validation": {"score": cross_validation, "max": 10, "details": "matches existing opportunities"},
            "domain_reputation": {"score": reputation, "max": 10, "details": "domain age from qualification"},
            "boost": {"score": float(source.trust_score_boost or 0), "max": 30, "details": "admin/employer verified boost"},
        }
        source.updated_at = utc_now()
        await source.save()
        return source

    def _field_completeness_score(self, samples: list[dict[str, Any]]) -> float:
        if not samples:
            return 0
        fields = ["title", "company", "location", "apply_url", "description_preview", "opportunity_type"]
        avg = sum(sum(1 for field in fields if row.get(field)) / len(fields) for row in samples) / len(samples)
        if avg >= 0.8:
            return 20
        if avg >= 0.6:
            return 15
        if avg >= 0.4:
            return 10
        return 0

    def _relevance_score(self, samples: list[dict[str, Any]]) -> float:
        if not samples:
            return 0
        per_item = 20 / max(1, len(samples))
        score = 0.0
        for row in samples:
            haystack = " ".join(str(row.get(field) or "") for field in ["title", "location", "description_preview", "stipend_text", "opportunity_type"]).lower()
            if any(term in haystack for term in INDIAN_CITY_TERMS) or "remote" in haystack:
                score += per_item * 0.45
            if "₹" in haystack or "inr" in haystack or "student" in haystack or "fresher" in haystack:
                score += per_item * 0.25
            if str(row.get("opportunity_type") or "").lower() in {"internship", "job", "hackathon", "scholarship", "research"}:
                score += per_item * 0.30
        return round(min(20, score), 2)

    async def _legitimacy_score(self, source: DiscoveredSource, samples: list[dict[str, Any]]) -> float:
        score = 0.0
        haystack = " ".join([source.name or "", source.domain, *[str(row.get("company") or "") for row in samples]]).lower()
        if any(term in haystack for term in LEGITIMATE_EMPLOYER_TERMS):
            score += 5
        if await DiscoveredSource.find_one(
            {
                "status": SourceStatus.promoted.value,
                "sample_opportunities.0": {"$exists": True},
            }
        ):
            score += 5
        if source.source_type == "company_careers" and source.domain:
            score += 5
        return min(15, score)

    async def _cross_validation_score(self, samples: list[dict[str, Any]]) -> float:
        matches = 0
        for row in samples:
            title = str(row.get("title") or "").strip()
            company = str(row.get("company") or "").strip()
            if not title:
                continue
            filters: list[Any] = [Opportunity.title == title]
            if company:
                filters.append(Opportunity.university == company)
            if await Opportunity.find_one(*filters):
                matches += 1
        if matches >= 2:
            return 10
        if matches == 1:
            return 5
        return 0

    def _domain_reputation_score(self, source: DiscoveredSource) -> float:
        details = source.qualification_details or {}
        notes = str((details.get("domain_age") or {}).get("notes") or "")
        match = re.search(r"age_days=(\d+)", notes)
        if not match:
            return 5
        age_days = int(match.group(1))
        if age_days >= 365 * 3:
            return 10
        if age_days >= 365:
            return 6
        return 2

    async def promote_source(self, source_id: str | PydanticObjectId, *, promoted_by: str = "auto") -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        if not source.trust_score:
            source = await self.score_source(source.id)
        scraper_key = source.scraper_key or source_key_from_domain(source.domain, source.source_type)
        registration = await ScraperRegistration.find_one(ScraperRegistration.scraper_key == scraper_key)
        if registration is None:
            registration = ScraperRegistration(
                scraper_key=scraper_key,
                source_name=source.name or source.domain,
                domain=source.domain,
                careers_url=source.url,
                source_type=source.source_type,
                extraction_method=str((source.parser_template or {}).get("extraction_method") or "llm_css"),
                parser_template=source.parser_template or {},
                trust_score=float(source.trust_score or 0),
                discovered_source_id=str(source.id),
            )
            await registration.insert()
        else:
            registration.status = ScraperRegistrationStatus.active
            registration.parser_template = source.parser_template or registration.parser_template
            registration.trust_score = float(source.trust_score or 0)
            registration.updated_at = utc_now()
            await registration.save()

        probation_rows = await ProbationOpportunity.find_many(ProbationOpportunity.discovered_source_id == source.id).to_list()
        inserted = 0
        for row in probation_rows:
            if await Opportunity.find_one(Opportunity.url == row.url):
                continue
            payload = row.raw_payload or {}
            opportunity = Opportunity(
                title=row.title,
                description=str(payload.get("description_preview") or payload.get("description") or row.title),
                url=row.url,
                university=row.company or source.name or source.domain,
                source=source.name or source.domain,
                source_id=str(source.id),
                domain=source.domain,
                location=payload.get("location"),
                work_mode=payload.get("work_mode"),
                stipend=payload.get("stipend_text") or payload.get("stipend"),
                opportunity_type=str(payload.get("opportunity_type") or "Job").title(),
                last_seen_at=utc_now(),
                updated_at=utc_now(),
            )
            apply_trust_assessment(opportunity, assess_opportunity_trust(opportunity))
            try:
                await opportunity.insert()
                inserted += 1
            except DuplicateKeyError:
                continue

        source.status = SourceStatus.promoted
        source.promoted_at = utc_now()
        source.promoted_by = promoted_by
        source.scraper_key = scraper_key
        source.total_opportunities_contributed += inserted
        source.updated_at = utc_now()
        await source.save()
        await notification_service.notify(
            "source.promoted",
            {
                "name": source.name or source.domain,
                "domain": source.domain,
                "trust_score": source.trust_score,
                "opportunity_type": source.source_type,
            },
        )
        await self._credit_submitter(source)
        return source

    async def reject_source(self, source_id: str | PydanticObjectId, *, reason: str, actor: str) -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        source.status = SourceStatus.rejected
        source.rejection_reason = reason
        source.rejected_at = utc_now()
        source.admin_reviewed_by = actor
        source.admin_reviewed_at = utc_now()
        source.updated_at = utc_now()
        await source.save()
        return source

    async def _credit_submitter(self, source: DiscoveredSource) -> None:
        if source.discovery_method != DiscoveryMethod.user_submission or not source.discovered_by:
            return
        try:
            user_id = _object_id(source.discovered_by)
            profile = await Profile.find_one(Profile.user_id == user_id)
            if profile:
                profile.incoscore = float(profile.incoscore or 0) + 10
                await profile.save()
        except Exception:
            logger.debug("Failed to credit source submitter", exc_info=True)


class TemplateDrivenScraper:
    def __init__(self, http_client: SourceHttpClient | None = None) -> None:
        self.http_client = http_client or SourceHttpClient(timeout_seconds=10)

    async def scrape(self, registration: ScraperRegistration) -> ScraperRunResult:
        template = registration.parser_template or {}
        method = str(template.get("extraction_method") or registration.extraction_method or "llm_css")
        if method == "schema_org":
            return await self._scrape_schema_org(registration)
        if method.startswith("ats_"):
            return await self._scrape_ats(registration, method)
        return await self._scrape_with_css_template(registration)

    async def _scrape_schema_org(self, registration: ScraperRegistration) -> ScraperRunResult:
        page = await self.http_client.fetch(registration.careers_url, timeout_seconds=10)
        soup = BeautifulSoup(page.text or "", "html.parser")
        extractor = AdaptiveExtractionService(http_client=self.http_client)
        rows = [
            extractor._map_schema_job(row, page.final_url)
            for row in _extract_jobposting_objects(
                [_safe_json_loads(script.string or script.get_text() or "") for script in soup.find_all("script", attrs={"type": "application/ld+json"})]
            )
        ]
        valid = [row for row in rows if row.get("title") and row.get("apply_url")]
        return ScraperRunResult(items=valid, items_parsed=len(valid), parse_success_rate=1.0 if rows else 0.0)

    async def _scrape_ats(self, registration: ScraperRegistration, method: str) -> ScraperRunResult:
        source = DiscoveredSource(
            url=registration.careers_url,
            domain=registration.domain,
            name=registration.source_name,
            source_type=registration.source_type,
            discovery_method=DiscoveryMethod.admin_manual,
        )
        extractor = AdaptiveExtractionService(http_client=self.http_client)
        rows = await extractor._extract_ats(
            {"method": method, "slug": str((registration.parser_template or {}).get("ats_slug") or registration.domain.split(".")[0])},
            source,
            registration.careers_url,
        )
        valid = [row for row in rows if row.get("title") and row.get("apply_url")]
        return ScraperRunResult(items=valid, items_parsed=len(valid), parse_success_rate=(len(valid) / max(1, len(rows))))

    async def _scrape_with_css_template(self, registration: ScraperRegistration) -> ScraperRunResult:
        template = registration.parser_template or {}
        base_url = registration.careers_url
        listing_selector = str(template.get("listing_selector") or "[data-job-id], .job, .opening, article, li")
        title_selector = str(template.get("title_selector") or "h1,h2,h3,h4,[class*=title],[class*=role]")
        apply_selector = str(template.get("apply_link_selector") or "a[href]")
        max_pages = max(1, min(10, int(template.get("max_pages") or 1)))
        pagination_pattern = template.get("pagination_pattern")
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for page_number in range(1, max_pages + 1):
            page_url = base_url if page_number == 1 or not pagination_pattern else urljoin(base_url, str(pagination_pattern).replace("{n}", str(page_number)))
            try:
                page = await self.http_client.fetch(page_url, timeout_seconds=10)
                soup = BeautifulSoup(page.text or "", "html.parser")
                for element in soup.select(listing_selector)[:50]:
                    title_node = element.select_one(title_selector)
                    link = element.select_one(apply_selector)
                    title = title_node.get_text(" ", strip=True) if title_node else element.get_text(" ", strip=True)[:90]
                    href = link.get("href") if link else page.final_url
                    if not title or not href:
                        continue
                    text = element.get_text(" ", strip=True)
                    rows.append(
                        {
                            "title": title,
                            "company": registration.source_name,
                            "location": _extract_location_hint(text),
                            "work_mode": _extract_work_mode_hint(text),
                            "apply_url": normalize_url(urljoin(page.final_url, str(href))),
                            "description_preview": text[:200],
                            "tags": _extract_skill_tags(text),
                            "opportunity_type": "internship" if "intern" in text.lower() else "job",
                        }
                    )
            except Exception as exc:
                errors.append(f"{page_url}:{exc}")
        valid = [row for row in rows if row.get("title") and row.get("apply_url")]
        return ScraperRunResult(
            items=valid,
            items_parsed=len(valid),
            parse_success_rate=len(valid) / max(1, len(rows)),
            errors=errors,
        )


class ProbationManager:
    def __init__(self, scraper: TemplateDrivenScraper | None = None, trust_engine: TrustScoringEngine | None = None) -> None:
        self.scraper = scraper or TemplateDrivenScraper()
        self.trust_engine = trust_engine or TrustScoringEngine()

    async def run_probation_scrape(self, source_id: str | PydanticObjectId) -> DiscoveredSource:
        source = await DiscoveredSource.get(_object_id(source_id))
        if source is None:
            raise ValueError("source_not_found")
        registration = ScraperRegistration(
            scraper_key=source.scraper_key or source_key_from_domain(source.domain, source.source_type),
            source_name=source.name or source.domain,
            domain=source.domain,
            careers_url=source.url,
            source_type=source.source_type,
            extraction_method=str((source.parser_template or {}).get("extraction_method") or "llm_css"),
            parser_template=source.parser_template or {},
            trust_score=float(source.trust_score or 0),
            discovered_source_id=str(source.id),
        )
        run_number = int(source.probation_runs or 0) + 1
        try:
            result = await self.scraper.scrape(registration)
            passed_quality = 0
            for row in result.items:
                quality_score = self._quality_score(row)
                if quality_score > 40:
                    passed_quality += 1
                try:
                    await ProbationOpportunity(
                        discovered_source_id=source.id,
                        scraper_key=registration.scraper_key,
                        title=str(row.get("title") or "")[:300],
                        company=str(row.get("company") or registration.source_name),
                        url=str(row.get("apply_url") or row.get("url")),
                        raw_payload=row,
                        quality_score=quality_score,
                        run_number=run_number,
                    ).insert()
                except Exception as exc:
                    source.probation_failures.append(f"probation_item_insert:{exc}")
            source.probation_runs = run_number
            source.probation_items_fetched.append(len(result.items))
            source.probation_items_passed_quality.append(passed_quality)
            source.probation_parse_rates.append(result.parse_success_rate)
            source.last_scraped_at = utc_now()
            source.consecutive_failures = 0 if result.items else int(source.consecutive_failures or 0) + 1
            if result.errors:
                source.probation_failures.extend(result.errors[:3])
            if source.trust_score is None:
                await self.trust_engine.score_source(source.id)
                source = await DiscoveredSource.get(source.id) or source
            await self._evaluate_after_probation(source)
        except Exception as exc:
            source.probation_runs = run_number
            source.probation_items_fetched.append(0)
            source.probation_items_passed_quality.append(0)
            source.probation_parse_rates.append(0.0)
            source.probation_failures.append(str(exc))
            source.consecutive_failures += 1
        source.updated_at = utc_now()
        await source.save()
        return source

    def _quality_score(self, row: dict[str, Any]) -> float:
        assessment = assess_opportunity_trust(
            {
                "title": row.get("title") or "",
                "description": row.get("description_preview") or "",
                "url": row.get("apply_url") or row.get("url") or "",
                "source": row.get("company") or "",
                "university": row.get("company") or "Unknown",
            }
        )
        return max(0.0, min(100.0, 100 - assessment.risk_score))

    async def _evaluate_after_probation(self, source: DiscoveredSource) -> None:
        min_runs = int(getattr(settings, "PROBATION_MIN_RUNS", 3))
        if int(source.probation_runs or 0) < min_runs:
            return
        trust_score = float(source.trust_score or 0)
        rates = list(source.probation_parse_rates or [])
        avg_parse_rate = sum(rates) / max(1, len(rates))
        items_ok = all(items >= 2 for items in (source.probation_items_fetched or [])[-min_runs:])
        quality_ok = all(items >= 2 for items in (source.probation_items_passed_quality or [])[-min_runs:])
        if (
            trust_score >= float(getattr(settings, "TRUST_MIN_SCORE_AUTO_PROMOTE", 70))
            and items_ok
            and quality_ok
            and avg_parse_rate >= float(getattr(settings, "PROBATION_MIN_PARSE_RATE", 0.70))
            and not source.admin_hold
            and not source.requires_admin_review
        ):
            await self.trust_engine.promote_source(source.id, promoted_by="auto")
            return
        if trust_score < float(getattr(settings, "TRUST_MIN_SCORE_REQUIRE_REVIEW", 55)) or avg_parse_rate < 0.40:
            source.status = SourceStatus.rejected
            source.rejection_reason = f"probation_failed:trust={trust_score:.1f},parse_rate={avg_parse_rate:.2f}"
            source.rejected_at = utc_now()
            return
        source.requires_admin_review = True
        await notification_service.notify(
            "source.review_required",
            {"domain": source.domain, "trust_score": source.trust_score, "reason": "probation_borderline"},
        )

    async def run_all_probation_sources(self, *, limit: int = 100) -> dict[str, Any]:
        sources = await DiscoveredSource.find_many(DiscoveredSource.status == SourceStatus.probation).limit(limit).to_list()
        processed = 0
        for source in sources:
            await self.run_probation_scrape(source.id)
            processed += 1
        return {"processed": processed}


class ScraperRegistry:
    async def all_active(self) -> list[ScraperRegistration]:
        return await ScraperRegistration.find_many(ScraperRegistration.status == ScraperRegistrationStatus.active).to_list()

    async def get(self, scraper_key: str) -> Optional[ScraperRegistration]:
        return await ScraperRegistration.find_one(ScraperRegistration.scraper_key == scraper_key)

    async def register(self, registration: ScraperRegistration) -> ScraperRegistration:
        existing = await self.get(registration.scraper_key)
        if existing:
            updates = registration.model_dump(exclude={"id"})
            for field_name, value in updates.items():
                setattr(existing, field_name, value)
            existing.updated_at = utc_now()
            await existing.save()
            return existing
        await registration.insert()
        return registration

    async def pause(self, scraper_key: str) -> Optional[ScraperRegistration]:
        row = await self.get(scraper_key)
        if row:
            row.status = ScraperRegistrationStatus.paused
            row.updated_at = utc_now()
            await row.save()
        return row

    async def quarantine(self, scraper_key: str, reason: str, *, increment_failure: bool = False) -> Optional[ScraperRegistration]:
        row = await self.get(scraper_key)
        if row:
            row.status = ScraperRegistrationStatus.quarantined
            if increment_failure:
                row.consecutive_failures += 1
            row.health_score = min(float(row.health_score or 100.0), 25.0)
            row.updated_at = utc_now()
            await row.save()
            if row.discovered_source_id:
                source = await DiscoveredSource.get(_object_id(row.discovered_source_id))
                if source:
                    source.status = SourceStatus.quarantined
                    source.retry_after = utc_now() + timedelta(days=30)
                    source.last_health_reason = reason
                    source.updated_at = utc_now()
                    await source.save()
            await notification_service.notify("source.quarantined", {"scraper_key": scraper_key, "reason": reason})
        return row


class SourceHealthMonitor:
    def __init__(self, registry: ScraperRegistry | None = None) -> None:
        self.registry = registry or ScraperRegistry()

    async def run(self) -> dict[str, Any]:
        rows = await self.registry.all_active()
        quarantined = 0
        for row in rows:
            reason = self._quarantine_reason(row)
            if reason:
                await self.registry.quarantine(row.scraper_key, reason)
                quarantined += 1
        return {"checked": len(rows), "quarantined": quarantined}

    def _quarantine_reason(self, row: ScraperRegistration) -> Optional[str]:
        if int(row.consecutive_failures or 0) >= 3:
            return "consecutive_failures"
        if float(row.health_score or 0) < 30:
            return "low_health_score"
        if int(row.stale_template_failures or 0) >= 2:
            return "stale_template_refresh_failed"
        if row.total_yield > 0 and row.last_scraped_at and row.last_scraped_at < utc_now() - timedelta(days=7):
            return "zero_yield_for_7_days"
        return None


class NotificationService:
    async def notify(self, event: str, payload: dict[str, Any]) -> None:
        webhook = (getattr(settings, "ADMIN_WEBHOOK_URL", "") or "").strip()
        if not webhook or httpx is None:
            return
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(webhook, json={"event": event, "payload": payload, "created_at": utc_now().isoformat()})
        except Exception:
            logger.debug("Admin webhook delivery failed", exc_info=True)


class SeedExpander:
    async def expand_from_linkedin(self) -> dict[str, Any]:
        if not (getattr(settings, "LINKEDIN_API_KEY", "") or "").strip():
            return {"added": 0, "skipped": "LINKEDIN_API_KEY not configured"}
        return {"added": 0, "skipped": "linkedin_api_integration_not_enabled"}


class EmployerClaimService:
    async def create_claim(self, *, user: User, careers_url: str, company_name: str) -> EmployerCareersClaim:
        profile = await Profile.find_one(Profile.user_id == user.id)
        company_domain = normalize_domain(getattr(profile, "company_website", "") or str(user.email).split("@")[-1])
        normalized_url = normalize_url(careers_url)
        claim_domain = normalize_domain(urlparse(normalized_url).netloc)
        if company_domain and claim_domain != company_domain and not claim_domain.endswith(f".{company_domain}"):
            raise ValueError("careers_url_domain_mismatch")
        claim = EmployerCareersClaim(
            employer_user_id=user.id,
            company_name=company_name,
            company_domain=claim_domain,
            careers_url=normalized_url,
            verification_token=f"vv-verify-{secrets.token_urlsafe(24)}",
        )
        await claim.insert()
        return claim

    async def verify_claim(self, *, claim: EmployerCareersClaim) -> EmployerCareersClaim:
        page = await SourceHttpClient(timeout_seconds=10).fetch(claim.careers_url, timeout_seconds=10)
        if claim.verification_token not in page.text:
            raise ValueError("verification_token_not_found")
        source = await DiscoveredSource.find_one(DiscoveredSource.domain == claim.company_domain)
        if source is None:
            source = DiscoveredSource(
                url=claim.careers_url,
                domain=claim.company_domain,
                name=claim.company_name,
                source_type="company_careers",
                discovery_method=DiscoveryMethod.employer_claim,
                discovered_by=str(claim.employer_user_id),
                status=SourceStatus.qualified,
                trust_score_boost=15,
                requires_admin_review=True,
            )
            await source.insert()
        else:
            source.status = SourceStatus.qualified
            source.trust_score_boost = max(float(source.trust_score_boost or 0), 15)
            await source.save()
        claim.verification_status = "verified"
        claim.verified_at = utc_now()
        claim.discovered_source_id = str(source.id)
        await claim.save()
        await RedisQueue().push(QUEUE_SOURCE_EXTRACTION, str(source.id))
        return claim

    async def latest_for_user(self, user: User) -> Optional[EmployerCareersClaim]:
        rows = await EmployerCareersClaim.find_many(EmployerCareersClaim.employer_user_id == user.id).sort("-created_at").limit(1).to_list()
        return rows[0] if rows else None


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return None


def _extract_json_object(value: str) -> Any:
    raw = str(value or "")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    return _safe_json_loads(raw[start : end + 1])


def _join_non_empty(values: Iterable[Any]) -> Optional[str]:
    rows = [str(value).strip() for value in values if str(value or "").strip()]
    return ", ".join(rows) if rows else None


def _extract_location_hint(text: str) -> Optional[str]:
    lower = str(text or "").lower()
    for term in sorted(INDIAN_CITY_TERMS, key=len, reverse=True):
        if term in lower:
            return term.title()
    if "remote" in lower:
        return "Remote"
    return None


def _extract_work_mode_hint(text: str) -> Optional[str]:
    lower = str(text or "").lower()
    if "hybrid" in lower:
        return "hybrid"
    if "remote" in lower or "work from home" in lower:
        return "remote"
    if "onsite" in lower or "on-site" in lower:
        return "onsite"
    return None


def _extract_skill_tags(text: str) -> list[str]:
    known = ["python", "java", "javascript", "typescript", "react", "node", "sql", "aws", "machine learning", "data science"]
    lower = str(text or "").lower()
    return [item for item in known if item in lower][:8]


source_discovery_engine = SourceDiscoveryEngine()
source_qualification_service = SourceQualificationService()
adaptive_extraction_service = AdaptiveExtractionService()
trust_scoring_engine = TrustScoringEngine()
probation_manager = ProbationManager(trust_engine=trust_scoring_engine)
scraper_registry = ScraperRegistry()
source_health_monitor = SourceHealthMonitor(registry=scraper_registry)
notification_service = NotificationService()
seed_expander = SeedExpander()
employer_claim_service = EmployerClaimService()
