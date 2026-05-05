from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import numpy as np
import pymongo
import requests
from bs4 import BeautifulSoup
from beanie.odm.operators.find.comparison import In
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import settings
from app.core.time import utc_now
from app.services.opportunity_trust import apply_trust_assessment, apply_trust_assessment_preserving_review, assess_opportunity_trust

logger = logging.getLogger(__name__)


IVY_LEAGUE_FEEDS: list[tuple[str, str]] = [
    ("Harvard University", "https://news.harvard.edu/gazette/feed/"),
    ("Yale University", "https://news.yale.edu/news-rss"),
    ("Princeton University", "https://www.princeton.edu/feed/"),
    ("Columbia University", "https://news.columbia.edu/feed"),
    ("University of Pennsylvania", "https://penntoday.upenn.edu/rss.xml"),
    # Brown/Dartmouth primary news pages currently do not expose stable public RSS URLs.
    ("Cornell University", "https://news.cornell.edu/taxonomy/term/81/feed"),
]

OPPORTUNITY_KEYWORDS = {
    "scholarship",
    "fellowship",
    "internship",
    "conference",
    "workshop",
    "hackathon",
    "competition",
    "grant",
    "call for papers",
    "applications open",
    "apply now",
    "student program",
    "research opportunity",
}

TYPE_HINTS = {
    "Scholarship": {"scholarship", "grant"},
    "Internship": {"internship"},
    "Conference": {"conference", "symposium"},
    "Workshop": {"workshop", "bootcamp"},
    "Hackathon": {"hackathon"},
    "Research": {"research", "fellowship", "call for papers"},
    "Competition": {"competition", "challenge", "contest"},
}

UNSTOP_CATEGORIES = ["hackathons", "quiz", "workshops-webinars", "conferences"]

INTERNSHALA_LISTINGS: list[tuple[str, str]] = [
    ("https://internshala.com/jobs/software-development-jobs/", "Job"),
    ("https://internshala.com/jobs/data-science-jobs/", "Job"),
    ("https://internshala.com/internships/computer-science-internship/", "Internship"),
    ("https://internshala.com/internships/data-science-internship/", "Internship"),
]

HACK2SKILL_EVENT_LISTINGS: list[str] = [
    "https://hack2skill.com",
]

FRESHERSWORLD_LISTINGS: list[tuple[str, str]] = [
    ("https://www.freshersworld.com/jobs/category/it-software-job-vacancies", "Job"),
]

INDEED_INDIA_LISTINGS: list[tuple[str, str]] = [
    (
        "https://in.indeed.com/jobs?q=work+from+home&l=&sc=0kf%3Aattr%28VDTG7%29%3B&from=searchOnDesktopSerp&vjk=fe4dcd039aaba3cd",
        "Job",
    ),
]

GENERIC_PORTAL_LISTINGS: list[dict[str, Any]] = [
    {
        "source": "linkedin",
        "label": "LinkedIn",
        "default_type": "Job",
        "default_university": "LinkedIn Recruiters",
        "listings": [
            "https://www.linkedin.com/jobs/search/?keywords=internship%20OR%20fresher%20OR%20entry%20level&location=India",
        ],
    },
    {
        "source": "glassdoor",
        "label": "Glassdoor",
        "default_type": "Job",
        "default_university": "Glassdoor Employers",
        "listings": [
            "https://www.glassdoor.co.in/Job/india-internship-jobs-SRCH_IL.0,5_IN115_KO6,16.htm",
        ],
    },
    {
        "source": "foundit",
        "label": "Foundit",
        "default_type": "Job",
        "default_university": "Foundit Recruiters",
        "listings": [
            "https://www.foundit.in/srp/results?query=internship&locations=India",
        ],
    },
    {
        "source": "devfolio",
        "label": "Devfolio",
        "default_type": "Hackathon",
        "default_university": "Devfolio",
        "listings": [
            "https://devfolio.co/hackathons",
        ],
    },
    {
        "source": "hackerearth",
        "label": "HackerEarth",
        "default_type": "Competition",
        "default_university": "HackerEarth",
        "listings": [
            "https://www.hackerearth.com/challenges/hackathon/",
            "https://www.hackerearth.com/challenges/competitive/",
        ],
    },
    {
        "source": "devpost",
        "label": "Devpost",
        "default_type": "Hackathon",
        "default_university": "Devpost",
        "listings": [
            "https://devpost.com/hackathons",
        ],
    },
    {
        "source": "techgig",
        "label": "TechGig",
        "default_type": "Competition",
        "default_university": "TechGig",
        "listings": [
            "https://www.techgig.com/challenge",
        ],
    },
    {
        "source": "reskilll",
        "label": "Reskilll",
        "default_type": "Hackathon",
        "default_university": "Reskilll",
        "listings": [
            "https://reskilll.com/hackathons",
        ],
    },
    {
        "source": "aicte_internship",
        "label": "AICTE Internship Portal",
        "default_type": "Internship",
        "default_university": "AICTE",
        "listings": [
            "https://internship.aicte-india.org/",
        ],
    },
    {
        "source": "smartinternz",
        "label": "SmartInternz",
        "default_type": "Internship",
        "default_university": "SmartInternz",
        "listings": [
            "https://smartinternz.com/internships",
        ],
    },
    {
        "source": "makeintern",
        "label": "MakeIntern",
        "default_type": "Internship",
        "default_university": "MakeIntern",
        "listings": [
            "https://www.makeintern.com/",
        ],
    },
    {
        "source": "letsintern",
        "label": "LetsIntern",
        "default_type": "Internship",
        "default_university": "LetsIntern",
        "listings": [
            "https://www.letsintern.com/",
        ],
    },
    {
        "source": "handshake",
        "label": "Handshake",
        "default_type": "Internship",
        "default_university": "Handshake",
        "listings": [
            "https://joinhandshake.com/students/",
        ],
    },
    {
        "source": "wellfound",
        "label": "Wellfound",
        "default_type": "Job",
        "default_university": "Wellfound Startups",
        "listings": [
            "https://wellfound.com/jobs",
        ],
    },
    {
        "source": "ycombinator_jobs",
        "label": "Y Combinator Jobs",
        "default_type": "Job",
        "default_university": "Y Combinator Startups",
        "listings": [
            "https://www.ycombinator.com/jobs",
        ],
    },
    {
        "source": "wayup",
        "label": "WayUp",
        "default_type": "Internship",
        "default_university": "WayUp Employers",
        "listings": [
            "https://www.wayup.com/s/internships/",
        ],
    },
    {
        "source": "chegg_internships",
        "label": "Chegg Internships",
        "default_type": "Internship",
        "default_university": "Chegg",
        "listings": [
            "https://www.chegg.com/internships",
        ],
    },
    {
        "source": "kaggle",
        "label": "Kaggle",
        "default_type": "Competition",
        "default_university": "Kaggle",
        "listings": [
            "https://www.kaggle.com/competitions",
        ],
    },
    {
        "source": "codeforces",
        "label": "Codeforces",
        "default_type": "Competition",
        "default_university": "Codeforces",
        "listings": [
            "https://codeforces.com/contests",
        ],
    },
    {
        "source": "geeksforgeeks_jobs",
        "label": "GeeksforGeeks Jobs",
        "default_type": "Job",
        "default_university": "GeeksforGeeks",
        "listings": [
            "https://www.geeksforgeeks.org/jobs/",
        ],
    },
    {
        "source": "promilo",
        "label": "Promilo",
        "default_type": "Job",
        "default_university": "Promilo",
        "listings": [
            "https://promilo.com/",
        ],
    },
]

GENERIC_OPPORTUNITY_KEYWORDS = {
    "job",
    "jobs",
    "hiring",
    "career",
    "internship",
    "intern",
    "hackathon",
    "competition",
    "contest",
    "challenge",
    "event",
    "fellowship",
    "opening",
    "opportunity",
    "round",
}

GENERIC_NON_OPPORTUNITY_ANCHORS = {
    "about",
    "about us",
    "contact",
    "careers",
    "pricing",
    "help",
    "privacy",
    "terms",
    "sign in",
    "signin",
    "log in",
    "login",
    "register",
    "sign up",
    "home",
    "learn more",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def _collapse_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%a %b %d %Y", "%B %d, %Y", "%b %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _dedupe_by_url(records: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for record in records:
        url = (record.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(record)
    return deduped


def _extract_deadline_from_text(text: str) -> datetime | None:
    if not text:
        return None
    patterns = [
        r"(?:deadline|apply by|applications? close(?:s)?|registration ends?)[:\s-]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        r"(?:deadline|apply by|applications? close(?:s)?|registration ends?)[:\s-]+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]
    lowered = _collapse_whitespace(text).lower()
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_datetime(match.group(1))
        if parsed:
            return parsed
    return None


def is_opportunity_active(opportunity: Any, now: datetime | None = None) -> bool:
    current_time = _to_naive_utc(now) or utc_now()
    deadline = _to_naive_utc(getattr(opportunity, "deadline", None))
    if deadline and deadline < current_time:
        return False

    return True


def _build_retry_session() -> requests.Session:
    retries = Retry(
        total=max(0, int(settings.SCRAPER_HTTP_RETRIES)),
        connect=max(0, int(settings.SCRAPER_HTTP_RETRIES)),
        read=max(0, int(settings.SCRAPER_HTTP_RETRIES)),
        backoff_factor=max(0.0, float(settings.SCRAPER_RETRY_BACKOFF)),
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _infer_opportunity_type(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    for opp_type, hints in TYPE_HINTS.items():
        if any(hint in text for hint in hints):
            return opp_type
    if "job" in text or "hiring" in text:
        return "Job"
    return "Opportunity"


class IvyLeagueRSSConnector:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; VidyaVerseIvyBot/1.0; +https://vidyaverse.local)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        }

    def _parse_feed(self, xml_text: str) -> list[dict]:
        entries: list[dict] = []
        root = ET.fromstring(xml_text)

        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = item.findtext("description") or item.findtext("content:encoded") or ""
                published_at = _parse_datetime(item.findtext("pubDate"))
                if title and link:
                    entries.append(
                        {
                            "title": title,
                            "link": link,
                            "description": description,
                            "published_at": published_at,
                        }
                    )
            return entries

        atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for entry in atom_entries:
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link = ""
            for link_tag in entry.findall("{http://www.w3.org/2005/Atom}link"):
                href = (link_tag.attrib.get("href") or "").strip()
                rel = (link_tag.attrib.get("rel") or "").strip()
                if href and rel in {"", "alternate"}:
                    link = href
                    break
            description = (
                entry.findtext("{http://www.w3.org/2005/Atom}summary")
                or entry.findtext("{http://www.w3.org/2005/Atom}content")
                or ""
            )
            published_raw = (
                entry.findtext("{http://www.w3.org/2005/Atom}published")
                or entry.findtext("{http://www.w3.org/2005/Atom}updated")
            )
            published_at = _parse_datetime(published_raw)
            if title and link:
                entries.append(
                    {
                        "title": title,
                        "link": link,
                        "description": description,
                        "published_at": published_at,
                    }
                )
        return entries

    def _looks_like_opportunity(self, title: str, description: str) -> bool:
        text = f"{title} {description}".lower()
        return any(keyword in text for keyword in OPPORTUNITY_KEYWORDS)

    def _infer_opportunity_type(self, title: str, description: str) -> str:
        return _infer_opportunity_type(title, description)

    def fetch_ivy_league_opportunities(self, max_items_per_school: int = 12) -> list[dict]:
        opportunities: list[dict] = []
        seen_urls: set[str] = set()

        for school_name, feed_url in IVY_LEAGUE_FEEDS:
            try:
                response = self.session.get(
                    feed_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                entries = self._parse_feed(response.text)
            except Exception as exc:
                logger.debug(
                    "[IvyConnector] Failed feed for %s (%s): %s",
                    school_name,
                    feed_url,
                    exc,
                )
                continue

            school_count = 0
            for entry in entries:
                if school_count >= max_items_per_school:
                    break
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link or link in seen_urls:
                    continue

                description = _strip_html(entry.get("description") or "")
                if not self._looks_like_opportunity(title, description):
                    continue

                parsed_deadline = self._extract_deadline(description)
                opportunity_type = self._infer_opportunity_type(title, description)
                summary = description[:420] + ("..." if len(description) > 420 else "")
                source_host = urlparse(link).netloc

                opportunities.append(
                    {
                        "title": title,
                        "description": f"{summary} [Source: {source_host}]",
                        "url": link,
                        "opportunity_type": opportunity_type,
                        "university": school_name,
                        "deadline": parsed_deadline,
                        "source": "ivy_rss",
                    }
                )
                seen_urls.add(link)
                school_count += 1

        return opportunities

    def _extract_deadline(self, text: str) -> datetime | None:
        date_patterns = [
            r"deadline[:\s]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"apply by[:\s]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"applications close[:\s]+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        ]
        lowered = text.lower()
        for pattern in date_patterns:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1)
            parsed = _parse_datetime(candidate)
            if parsed:
                return parsed
            try:
                parsed = datetime.strptime(candidate, "%B %d, %Y").replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                continue
        return None


class UnstopScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VidyaVerseBot",
            "Accept": "application/json, text/plain, */*",
        }

    def _build_api_urls(self, opp_type: str) -> list[str]:
        return [
            f"https://unstop.com/api/public/opportunity/search-result?opportunity={opp_type}&oppstatus=open",
            f"https://unstop.com/api/public/opportunity/search-result?opportunity={opp_type}",
        ]

    def fetch_unstop_opportunities(self, opp_type: str = "hackathons", max_items: int = 30) -> list[dict]:
        opportunities: list[dict] = []
        errors: list[str] = []

        for url in self._build_api_urls(opp_type):
            try:
                response = self.session.get(url, headers=self.headers, timeout=settings.SCRAPER_TIMEOUT_SECONDS)
                response.raise_for_status()
                payload = response.json()
                results = payload.get("data", {}).get("data", [])
                if not results:
                    continue

                for item in results:
                    raw_public_url = str(item.get("public_url") or "").strip()
                    if not raw_public_url:
                        continue
                    full_url = (
                        raw_public_url
                        if raw_public_url.startswith("http")
                        else f"https://unstop.com/{raw_public_url.lstrip('/')}"
                    )
                    raw_deadline = item.get("end_date") or item.get("updated_at")
                    parsed_deadline = _parse_datetime(raw_deadline)
                    description = _strip_html(item.get("details", ""))[:260]
                    opportunities.append(
                        {
                            "title": str(item.get("title") or "Unknown Title").strip(),
                            "description": (
                                f"{description}..." if description else "Opportunity details unavailable."
                            ),
                            "url": full_url,
                            "opportunity_type": str(item.get("type") or opp_type).replace("-", " ").title(),
                            "university": (
                                item.get("organization", {}) or {}
                            ).get("name", "Various"),
                            "deadline": parsed_deadline,
                            "source": "unstop",
                        }
                    )
                    if len(opportunities) >= max_items:
                        break
                if opportunities:
                    break
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        if errors and not opportunities:
            logger.debug("[Unstop] All fetch attempts failed: %s", "; ".join(errors))

        return _dedupe_by_url(opportunities)[:max_items]


class NaukriScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def _extract_from_cards(self, soup: BeautifulSoup) -> list[dict]:
        jobs: list[dict] = []
        cards = soup.select("article.jobTuple, div.srp-jobtuple-wrapper")
        for card in cards:
            title_elem = card.select_one("a.title")
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            job_url = (title_elem.get("href") or "").strip()
            if not job_url:
                continue
            company_elem = card.select_one("a.comp-name")
            company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"
            desc_elem = card.select_one("div.job-desc, span.job-desc")
            description = (
                desc_elem.get_text(strip=True)
                if desc_elem
                else f"IT job opportunity at {company}."
            )
            jobs.append(
                {
                    "title": title,
                    "description": f"{description[:220]}...",
                    "url": job_url,
                    "university": company,
                }
            )
        return jobs

    def _walk_json(self, node: Any) -> Iterable[dict]:
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from self._walk_json(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._walk_json(value)

    def _extract_from_ld_json(self, soup: BeautifulSoup) -> list[dict]:
        jobs: list[dict] = []
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        for script in scripts:
            raw = script.string or script.get_text()
            if not raw or not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except Exception:
                continue

            for node in self._walk_json(parsed):
                node_type = str(node.get("@type") or "").strip()
                payload = node
                if node_type == "ListItem" and isinstance(node.get("item"), dict):
                    payload = node["item"]
                    node_type = str(payload.get("@type") or "").strip()
                if node_type != "JobPosting":
                    continue

                title = str(payload.get("title") or "").strip()
                job_url = str(payload.get("url") or "").strip()
                company = "Unknown Company"
                hiring_org = payload.get("hiringOrganization")
                if isinstance(hiring_org, dict):
                    company = str(hiring_org.get("name") or company).strip()
                description = _strip_html(str(payload.get("description") or ""))
                if not title or not job_url:
                    continue

                jobs.append(
                    {
                        "title": title,
                        "description": f"{(description or f'IT job opportunity at {company}.')[:220]}...",
                        "url": job_url,
                        "university": company,
                    }
                )
        return jobs

    def _extract_with_playwright(self, max_items: int) -> list[dict]:
        """
        Dynamic-render fallback when Naukri HTML does not expose cards in static response.
        Uses Playwright only as a recovery path.
        """
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            logger.debug("[Naukri] Playwright fallback unavailable: %s", exc)
            return []

        opportunities: list[dict] = []
        search_urls = [
            "https://www.naukri.com/it-jobs?src=gnbjobs_homepage_srch",
            "https://www.naukri.com/software-developer-jobs",
        ]

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                for search_url in search_urls:
                    try:
                        page.goto(
                            search_url,
                            wait_until="domcontentloaded",
                            timeout=max(10000, settings.PLAYWRIGHT_TIMEOUT_MS),
                        )
                        page.wait_for_timeout(2500)
                        soup = BeautifulSoup(page.content(), "html.parser")
                        parsed_jobs = self._extract_from_cards(soup)
                        if not parsed_jobs:
                            parsed_jobs = self._extract_from_ld_json(soup)
                        for job in parsed_jobs:
                            opportunities.append(
                                {
                                    "title": job["title"],
                                    "description": job["description"],
                                    "url": job["url"],
                                    "opportunity_type": "Job",
                                    "university": job["university"],
                                    "deadline": _utcnow() + timedelta(days=30),
                                    "source": "naukri",
                                }
                            )
                            if len(opportunities) >= max_items:
                                break
                        if len(opportunities) >= max_items:
                            break
                    except Exception as exc:
                        logger.debug("[Naukri] Playwright URL failed %s: %s", search_url, exc)
                browser.close()
        except Exception as exc:
            logger.debug("[Naukri] Playwright fallback failed: %s", exc)

        return _dedupe_by_url(opportunities)[:max_items]

    def fetch_it_jobs(self, max_items: int = 25) -> list[dict]:
        opportunities: list[dict] = []
        search_urls = [
            "https://www.naukri.com/it-jobs?src=gnbjobs_homepage_srch",
            "https://www.naukri.com/software-developer-jobs",
        ]

        for search_url in search_urls:
            try:
                response = self.session.get(
                    search_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                parsed_jobs = self._extract_from_cards(soup)
                if not parsed_jobs:
                    parsed_jobs = self._extract_from_ld_json(soup)

                for job in parsed_jobs:
                    opportunities.append(
                        {
                            "title": job["title"],
                            "description": job["description"],
                            "url": job["url"],
                            "opportunity_type": "Job",
                            "university": job["university"],
                            "deadline": _utcnow() + timedelta(days=30),
                            "source": "naukri",
                        }
                    )
                    if len(opportunities) >= max_items:
                        break
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                logger.debug("[Naukri] Failed fetch from %s: %s", search_url, exc)

        if not opportunities and settings.SCRAPER_NAUKRI_ENABLE_PLAYWRIGHT_FALLBACK:
            opportunities.extend(self._extract_with_playwright(max_items=max_items))

        return _dedupe_by_url(opportunities)[:max_items]


class InternshalaScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _extract_cards(self, soup: BeautifulSoup, listing_url: str, default_type: str) -> list[dict]:
        opportunities: list[dict] = []
        for card in soup.select("div.individual_internship"):
            title_elem = card.select_one("a.job-title-href")
            company_elem = card.select_one("p.company-name")
            description_elem = card.select_one("div.about_job div.text")
            skill_nodes = card.select("div.job_skill")
            location_nodes = card.select("p.row-1-item.locations span a, p.row-1-item.locations span")
            salary_elem = card.select_one("div.row-1-item span.desktop, div.row-1-item span.mobile")
            experience_nodes = card.select("div.row-1-item span")

            title = _collapse_whitespace(title_elem.get_text(" ", strip=True) if title_elem else "")
            relative_url = (title_elem.get("href") or "").strip() if title_elem else ""
            company = _collapse_whitespace(company_elem.get_text(" ", strip=True) if company_elem else "")
            description = _collapse_whitespace(
                description_elem.get_text(" ", strip=True) if description_elem else ""
            )
            skills = [_collapse_whitespace(node.get_text(" ", strip=True)) for node in skill_nodes]
            skills = [skill for skill in skills if skill]
            locations = [
                _collapse_whitespace(node.get_text(" ", strip=True))
                for node in location_nodes
                if _collapse_whitespace(node.get_text(" ", strip=True))
            ]
            salary = _collapse_whitespace(salary_elem.get_text(" ", strip=True) if salary_elem else "")
            experience = ""
            for node in experience_nodes:
                value = _collapse_whitespace(node.get_text(" ", strip=True))
                if "year" in value.lower():
                    experience = value
                    break

            if not title or not relative_url:
                continue

            fragments = [description]
            if skills:
                fragments.append(f"Skills: {', '.join(skills[:8])}")
            if locations:
                fragments.append(f"Location: {', '.join(locations[:3])}")
            if salary:
                fragments.append(f"Compensation: {salary}")
            if experience:
                fragments.append(f"Experience: {experience}")

            final_description = " | ".join(fragment for fragment in fragments if fragment)
            opportunities.append(
                {
                    "title": title,
                    "description": final_description[:700],
                    "url": urljoin(listing_url, relative_url),
                    "opportunity_type": default_type,
                    "university": company or "Internshala Partner",
                    "deadline": _utcnow() + timedelta(days=30),
                    "source": "internshala",
                }
            )

        return opportunities

    def fetch_live_opportunities(self, max_items: int = 30) -> list[dict]:
        opportunities: list[dict] = []

        for listing_url, default_type in INTERNSHALA_LISTINGS:
            try:
                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                opportunities.extend(self._extract_cards(soup, listing_url, default_type))
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                logger.debug("[Internshala] Failed fetch from %s: %s", listing_url, exc)

        return _dedupe_by_url(opportunities)[:max_items]


class Hack2SkillScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _extract_cards(self, soup: BeautifulSoup, listing_url: str) -> list[dict]:
        opportunities: list[dict] = []

        for anchor in soup.select('a[href*="vision.hack2skill.com/event/"]'):
            container = anchor.find_parent(
                "div",
                class_=lambda value: value and "overflow-hidden" in value and "rounded-xl" in value,
            )
            if not container:
                continue

            title_node = container.select_one("h5[title]") or container.find("h5")
            title = _collapse_whitespace(
                (title_node.get("title") if title_node and title_node.has_attr("title") else "")
                or (title_node.get_text(" ", strip=True) if title_node else "")
            )
            url = (anchor.get("href") or "").strip()
            if not title or not url:
                continue

            meta_node = container.find("div", class_=lambda value: value and "py-1" in str(value))
            meta_line = _collapse_whitespace(meta_node.get_text(" ", strip=True) if meta_node else "")
            registration_text = ""
            deadline = None
            for label in container.find_all("h6"):
                label_text = _collapse_whitespace(label.get_text(" ", strip=True))
                if "registration ends" not in label_text.lower():
                    continue
                date_node = label.find_next_sibling("h5")
                registration_text = _collapse_whitespace(date_node.get_text(" ", strip=True) if date_node else "")
                deadline = _parse_datetime(registration_text)
                break

            fragments = []
            if meta_line:
                fragments.append(meta_line.replace("|", " | "))
            if registration_text:
                fragments.append(f"Registration ends: {registration_text}")

            description = " | ".join(fragment for fragment in fragments if fragment) or (
                "Live hackathon and upskilling opportunity listed on Hack2Skill."
            )

            opportunities.append(
                {
                    "title": title,
                    "description": description[:700],
                    "url": urljoin(listing_url, url),
                    "opportunity_type": _infer_opportunity_type(title, description),
                    "university": "Hack2Skill",
                    "deadline": deadline,
                    "source": "hack2skill",
                }
            )

        return opportunities

    def fetch_live_opportunities(self, max_items: int = 24) -> list[dict]:
        opportunities: list[dict] = []

        for listing_url in HACK2SKILL_EVENT_LISTINGS:
            try:
                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                opportunities.extend(self._extract_cards(soup, listing_url))
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                logger.debug("[Hack2Skill] Failed fetch from %s: %s", listing_url, exc)

        return _dedupe_by_url(opportunities)[:max_items]


class FreshersworldScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _extract_cards(self, soup: BeautifulSoup) -> list[dict]:
        opportunities: list[dict] = []

        for card in soup.select("div.job-container[job_display_url]"):
            title = _collapse_whitespace(
                (card.select_one(".job-new-title .wrap-title") or card.select_one(".job-new-title")).get_text(
                    " ",
                    strip=True,
                )
                if card.select_one(".job-new-title .wrap-title") or card.select_one(".job-new-title")
                else ""
            )
            title = re.sub(r"\s+(More|Less)\s*$", "", title).strip()
            url = (card.get("job_display_url") or "").strip()
            company = _collapse_whitespace(
                card.select_one(".company-name").get_text(" ", strip=True) if card.select_one(".company-name") else ""
            )
            location = _collapse_whitespace(
                card.select_one(".job-location").get_text(" ", strip=True) if card.select_one(".job-location") else ""
            )
            experience = _collapse_whitespace(
                card.select_one(".experience").get_text(" ", strip=True) if card.select_one(".experience") else ""
            )
            qualifications = [
                _collapse_whitespace(node.get_text(" ", strip=True))
                for node in card.select("span.qualifications")
                if _collapse_whitespace(node.get_text(" ", strip=True))
            ]
            description_text = _collapse_whitespace(
                card.select_one("span.desc").get_text(" ", strip=True) if card.select_one("span.desc") else ""
            )

            if not title or not url:
                continue

            fragments = [description_text]
            if location:
                fragments.append(f"Location: {location}")
            if experience:
                fragments.append(f"Experience: {experience}")
            if qualifications:
                fragments.append(f"Compensation: {qualifications[0]}")
            if len(qualifications) > 1:
                fragments.append(f"Eligibility: {qualifications[1]}")

            description = " | ".join(fragment for fragment in fragments if fragment) or (
                f"IT and software opportunity listed by {company or 'Freshersworld'}."
            )

            opportunities.append(
                {
                    "title": title,
                    "description": description[:700],
                    "url": url,
                    "opportunity_type": "Job",
                    "university": company or "Freshersworld Employer",
                    "deadline": None,
                    "source": "freshersworld",
                }
            )

        return opportunities

    def fetch_live_opportunities(self, max_items: int = 30) -> list[dict]:
        opportunities: list[dict] = []

        for listing_url, default_type in FRESHERSWORLD_LISTINGS:
            try:
                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                parsed = self._extract_cards(soup)
                if default_type:
                    for record in parsed:
                        record["opportunity_type"] = default_type
                opportunities.extend(parsed)
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                logger.debug("[Freshersworld] Failed fetch from %s: %s", listing_url, exc)

        return _dedupe_by_url(opportunities)[:max_items]


class IndeedIndiaScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _response_is_blocked(self, html: str) -> bool:
        lowered = html.lower()
        return "just a moment" in lowered or "enable javascript and cookies to continue" in lowered

    def _extract_cards(self, soup: BeautifulSoup) -> list[dict]:
        opportunities: list[dict] = []

        selectors = [
            "div.job_seen_beacon",
            "li div.cardOutline",
            "div.slider_container div.slider_item",
            "table.jobCard_mainContent",
        ]
        cards: list[Any] = []
        for selector in selectors:
            cards = soup.select(selector)
            if cards:
                break

        for card in cards:
            title_elem = (
                card.select_one("h2.jobTitle a")
                or card.select_one("a.jcs-JobTitle")
                or card.select_one("a[data-jk]")
                or card.select_one("a.tapItem")
            )
            company_elem = card.select_one('[data-testid="company-name"]') or card.select_one("span.companyName")
            location_elem = card.select_one('[data-testid="text-location"]') or card.select_one("div.companyLocation")
            desc_elem = card.select_one('[data-testid="job-snippet"]') or card.select_one("div.job-snippet")

            title = _collapse_whitespace(title_elem.get_text(" ", strip=True) if title_elem else "")
            job_url = (title_elem.get("href") or "").strip() if title_elem else ""
            if job_url and not job_url.startswith("http"):
                job_url = urljoin("https://in.indeed.com", job_url)

            if not title or not job_url:
                continue

            company = _collapse_whitespace(company_elem.get_text(" ", strip=True) if company_elem else "")
            location = _collapse_whitespace(location_elem.get_text(" ", strip=True) if location_elem else "")
            description = _collapse_whitespace(desc_elem.get_text(" ", strip=True) if desc_elem else "")
            final_description = (
                " | ".join(
                    fragment
                    for fragment in [
                        description,
                        f"Location: {location}" if location else "",
                        "Remote-friendly role indexed from Indeed India.",
                    ]
                    if fragment
                )
                or "Remote-friendly role indexed from Indeed India."
            )

            opportunities.append(
                {
                    "title": title,
                    "description": final_description[:700],
                    "url": job_url,
                    "opportunity_type": "Job",
                    "university": company or "Indeed India Employer",
                    "deadline": None,
                    "source": "indeed_india",
                }
            )

        return opportunities

    def fetch_live_opportunities(self, max_items: int = 20) -> list[dict]:
        opportunities: list[dict] = []
        errors: list[str] = []

        for listing_url, default_type in INDEED_INDIA_LISTINGS:
            try:
                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                if self._response_is_blocked(response.text):
                    errors.append("Blocked by Indeed India anti-bot challenge.")
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                parsed = self._extract_cards(soup)
                if default_type:
                    for record in parsed:
                        record["opportunity_type"] = default_type
                opportunities.extend(parsed)
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                errors.append(str(exc))

        if errors and not opportunities:
            raise RuntimeError("; ".join(errors))

        return _dedupe_by_url(opportunities)[:max_items]


class GenericOpportunityPortalScraper:
    def __init__(
        self,
        session: requests.Session | None = None,
        source_configs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.session = session or _build_retry_session()
        self.source_configs = {
            str(config.get("source") or "").strip().lower(): config
            for config in (source_configs or GENERIC_PORTAL_LISTINGS)
            if str(config.get("source") or "").strip()
        }
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _walk_json(self, node: Any) -> Iterable[dict]:
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from self._walk_json(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._walk_json(value)

    def _extract_from_ld_json(
        self,
        soup: BeautifulSoup,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        opportunities: list[dict] = []
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        for script in scripts:
            raw = script.string or script.get_text()
            if not raw or not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except Exception:
                continue

            for node in self._walk_json(parsed):
                node_type = str(node.get("@type") or "").strip()
                if node_type == "ListItem" and isinstance(node.get("item"), dict):
                    node = node["item"]
                    node_type = str(node.get("@type") or "").strip()

                if node_type not in {"JobPosting", "Event"}:
                    continue

                title = _collapse_whitespace(str(node.get("title") or node.get("name") or ""))
                url = _collapse_whitespace(str(node.get("url") or ""))
                if not title or not url:
                    continue
                if not url.startswith("http"):
                    url = urljoin(listing_url, url)

                description = _strip_html(str(node.get("description") or ""))
                if node_type == "Event":
                    start_raw = str(node.get("startDate") or "")
                    end_raw = str(node.get("endDate") or "")
                    deadline = _parse_datetime(end_raw) or _parse_datetime(start_raw)
                else:
                    valid_through = str(node.get("validThrough") or "")
                    deadline = _parse_datetime(valid_through) or _extract_deadline_from_text(description)

                organization = default_university
                hiring_org = node.get("hiringOrganization")
                if isinstance(hiring_org, dict):
                    organization = _collapse_whitespace(str(hiring_org.get("name") or organization))
                organizer = node.get("organizer")
                if isinstance(organizer, dict):
                    organization = _collapse_whitespace(str(organizer.get("name") or organization))

                final_description = _collapse_whitespace(description)
                if not final_description:
                    final_description = f"Opportunity indexed from {source_name.replace('_', ' ').title()}."

                opportunities.append(
                    {
                        "title": title[:220],
                        "description": final_description[:700],
                        "url": url,
                        "opportunity_type": default_type or _infer_opportunity_type(title, final_description),
                        "university": organization or default_university,
                        "deadline": deadline,
                        "source": source_name,
                    }
                )
        return opportunities

    def _looks_like_candidate(self, title: str, url: str) -> bool:
        if not title or not url:
            return False
        normalized_title = title.strip().lower()
        if normalized_title in GENERIC_NON_OPPORTUNITY_ANCHORS:
            return False
        if len(normalized_title) < 8 or len(normalized_title) > 220:
            return False

        if normalized_title.count(" ") <= 1 and len(normalized_title) < 18:
            return False

        lowered_url = url.lower()
        meaningful_path_tokens = (
            "/job",
            "/jobs",
            "/career",
            "/intern",
            "/fellow",
            "/hackathon",
            "/challenge",
            "/competition",
            "/contest",
            "/event",
            "/opportunit",
            "/round",
        )
        keyword_hit = any(keyword in normalized_title for keyword in GENERIC_OPPORTUNITY_KEYWORDS)
        path_hit = any(token in lowered_url for token in meaningful_path_tokens)
        return keyword_hit or path_hit

    def _extract_from_anchors(
        self,
        soup: BeautifulSoup,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        opportunities: list[dict] = []
        seen_urls: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            url = href if href.startswith("http") else urljoin(listing_url, href)
            url = url.split("#", 1)[0].strip()
            title = _collapse_whitespace(anchor.get_text(" ", strip=True))
            if not self._looks_like_candidate(title, url):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            container = anchor.find_parent(["article", "li", "section", "div"])
            context_text = _collapse_whitespace(container.get_text(" ", strip=True) if container else "")
            context_text = context_text.replace(title, "", 1).strip() if context_text.startswith(title) else context_text
            description = context_text[:700] if context_text else f"Opportunity indexed from {source_name}."
            deadline = _extract_deadline_from_text(context_text)

            opportunities.append(
                {
                    "title": title[:220],
                    "description": description[:700],
                    "url": url,
                    "opportunity_type": default_type or _infer_opportunity_type(title, description),
                    "university": default_university,
                    "deadline": deadline,
                    "source": source_name,
                }
            )

        return opportunities

    def fetch_live_opportunities(self, source_name: str, max_items: int = 12) -> list[dict]:
        normalized_source = source_name.strip().lower()
        source_config = self.source_configs.get(normalized_source)
        if not source_config:
            raise ValueError(f"Unsupported source: {source_name}")

        opportunities: list[dict] = []
        errors: list[str] = []
        listing_urls = source_config.get("listings") or []
        default_type = str(source_config.get("default_type") or "Opportunity")
        default_university = str(source_config.get("default_university") or source_config.get("label") or "Various")

        for listing_url in listing_urls:
            try:
                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                parsed = self._extract_from_ld_json(
                    soup=soup,
                    listing_url=listing_url,
                    source_name=normalized_source,
                    default_type=default_type,
                    default_university=default_university,
                )
                parsed.extend(
                    self._extract_from_anchors(
                        soup=soup,
                        listing_url=listing_url,
                        source_name=normalized_source,
                        default_type=default_type,
                        default_university=default_university,
                    )
                )
                opportunities.extend(parsed)
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                errors.append(f"{listing_url}: {exc}")

        opportunities = _dedupe_by_url(opportunities)[:max_items]
        if errors and not opportunities:
            raise RuntimeError("; ".join(errors))
        return opportunities


ivy_connector = IvyLeagueRSSConnector()
unstop_scraper = UnstopScraper()
naukri_scraper = NaukriScraper()
internshala_scraper = InternshalaScraper()
hack2skill_scraper = Hack2SkillScraper()
freshersworld_scraper = FreshersworldScraper()
indeed_india_scraper = IndeedIndiaScraper()
generic_portal_scraper = GenericOpportunityPortalScraper()

_scraper_lock = asyncio.Lock()
_scraper_runtime_state: dict[str, Any] = {
    "is_running": False,
    "runs_total": 0,
    "consecutive_failures": 0,
    "last_started_at": None,
    "last_finished_at": None,
    "last_successful_at": None,
    "last_status": "never_run",
    "last_report": None,
}


def get_scraper_runtime_status() -> dict[str, Any]:
    snapshot = copy.deepcopy(_scraper_runtime_state)
    snapshot["auto_update"] = {
        "enabled": bool(settings.SCRAPER_AUTORUN_ENABLED),
        "interval_minutes": max(1, int(settings.SCRAPER_INTERVAL_MINUTES)),
        "stale_refresh_minutes": max(1, int(settings.SCRAPER_MAX_STALENESS_MINUTES)),
        "on_demand_refresh_enabled": bool(settings.SCRAPER_ON_DEMAND_REFRESH_ENABLED),
    }
    return snapshot


def _new_source_report(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
    }


async def _delete_opportunities(records: Iterable[Any]) -> int:
    deleted_count = 0
    seen_ids: set[str] = set()
    for record in records:
        record_id = str(getattr(record, "id", ""))
        if record_id and record_id in seen_ids:
            continue
        if record_id:
            seen_ids.add(record_id)
        await record.delete()
        deleted_count += 1
    return deleted_count


async def _cleanup_inactive_opportunities(Opportunity) -> dict[str, int]:
    now = utc_now()
    cleanup_report = {
        "expired_deleted": 0,
        "stale_deleted": 0,
        "hard_stale_deleted": 0,
        "total_deleted": 0,
    }

    expired_records = await Opportunity.find_many({"deadline": {"$ne": None, "$lt": now}}).to_list()
    cleanup_report["expired_deleted"] = await _delete_opportunities(expired_records)
    cleanup_report["total_deleted"] = (
        cleanup_report["expired_deleted"]
        + cleanup_report["stale_deleted"]
        + cleanup_report["hard_stale_deleted"]
    )

    return cleanup_report


async def _insert_and_broadcast(
    opportunities: Iterable[dict],
    source_name: str,
    system_user_id,
    ai_system,
    Opportunity,
    Post,
) -> dict[str, int]:
    inserted_count = 0
    updated_count = 0
    failed_count = 0
    semantic_threshold = max(0.0, min(1.0, float(settings.SEMANTIC_DEDUP_THRESHOLD)))

    normalized_records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for opp_data in opportunities:
        url = (opp_data.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        classification = ai_system.classify_opportunity(
            f"{opp_data.get('title', '')} {opp_data.get('description', '')}"
        )
        normalized_payload = dict(opp_data)
        normalized_payload["url"] = url
        normalized_payload["deadline"] = _to_naive_utc(opp_data.get("deadline"))
        normalized_payload["domain"] = opp_data.get("domain") or classification["primary_domain"]
        normalized_payload["source"] = opp_data.get("source") or source_name.lower().replace(" ", "_")
        normalized_payload.update(assess_opportunity_trust(normalized_payload).as_update())
        normalized_records.append(normalized_payload)

    if len(normalized_records) > 1:
        from app.services.embedding_service import embedding_service

        semantic_texts = [
            f"{record.get('title', '')} {record.get('description', '')} {record.get('opportunity_type', '')}".strip()
            for record in normalized_records
        ]
        semantic_vectors = await embedding_service.embed_texts(semantic_texts)
        keep_indexes: list[int] = []

        for idx, vector in enumerate(semantic_vectors):
            is_duplicate = False
            for kept_idx in keep_indexes:
                similarity = float(np.dot(vector, semantic_vectors[kept_idx]))
                if similarity >= semantic_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                keep_indexes.append(idx)

        normalized_records = [normalized_records[idx] for idx in keep_indexes]

    existing_by_url: dict[str, Any] = {}
    if normalized_records:
        existing_records = await Opportunity.find_many(
            In(Opportunity.url, [record["url"] for record in normalized_records])
        ).to_list()
        existing_by_url = {record.url: record for record in existing_records}

    from app.services.vector_service import opportunity_vector_service

    if normalized_records:
        await opportunity_vector_service.rebuild()

    for normalized_payload in normalized_records:
        url = normalized_payload["url"]

        try:
            now_naive = utc_now()
            existing = existing_by_url.get(url)
            if existing:
                changed = False
                for field in ["title", "description", "opportunity_type", "university", "deadline", "source", "domain"]:
                    incoming = normalized_payload.get(field)
                    if incoming is None:
                        continue
                    if getattr(existing, field, None) != incoming:
                        setattr(existing, field, incoming)
                        changed = True
                next_assessment = assess_opportunity_trust(existing)
                if (
                    getattr(existing, "trust_status", None) != next_assessment.trust_status
                    or int(getattr(existing, "trust_score", 0) or 0) != next_assessment.trust_score
                    or int(getattr(existing, "risk_score", 0) or 0) != next_assessment.risk_score
                    or list(getattr(existing, "risk_reasons", []) or []) != next_assessment.risk_reasons
                    or list(getattr(existing, "verification_evidence", []) or []) != next_assessment.verification_evidence
                ):
                    apply_trust_assessment_preserving_review(existing, next_assessment)
                    changed = True
                existing.last_seen_at = now_naive
                if changed:
                    existing.updated_at = now_naive
                    updated_count += 1
                await existing.save()
                continue

            semantic_text = (
                f"{normalized_payload.get('title', '')} {normalized_payload.get('description', '')} "
                f"{normalized_payload.get('opportunity_type', '')}"
            ).strip()
            semantic_duplicates = await opportunity_vector_service.find_semantic_duplicates(
                semantic_text,
                threshold=semantic_threshold,
                top_k=1,
                exclude_urls=[url],
            )
            if semantic_duplicates:
                duplicate_url = semantic_duplicates[0].get("url")
                duplicate = await Opportunity.find_one(Opportunity.url == duplicate_url)
                if duplicate:
                    duplicate.last_seen_at = now_naive
                    await duplicate.save()
                    updated_count += 1
                    continue

            opportunity = Opportunity(
                **normalized_payload,
                updated_at=now_naive,
                last_seen_at=now_naive,
            )
            await opportunity.insert()
            inserted_count += 1

            if system_user_id:
                post_content = (
                    f"[{source_name}] New {opportunity.opportunity_type} at "
                    f"{opportunity.university}: '{opportunity.title}'."
                )
                await Post(
                    user_id=system_user_id,
                    domain=opportunity.domain or "General",
                    content=post_content,
                ).insert()
        except pymongo.errors.DuplicateKeyError:
            continue
        except Exception as exc:
            failed_count += 1
            print(f"[ScraperInsert] Failed to upsert '{normalized_payload.get('title', 'unknown')}': {exc}")

    if inserted_count or updated_count:
        await opportunity_vector_service.rebuild(force=True)

    return {"inserted": inserted_count, "updated": updated_count, "failed": failed_count}


async def run_scheduled_scrapers(force: bool = False) -> dict[str, Any]:
    """
    Resilient background job for live opportunity data ingestion:
    1) Ivy League feeds
    2) Unstop opportunities
    3) Core Indian opportunity boards (Naukri, Internshala, Hack2Skill,
       Freshersworld, and a best-effort Indeed India fetch)
    4) Additional student opportunity platforms (jobs, internships, hackathons,
       coding challenges, and global boards).

    Returns a structured run report with per-source stats.
    """
    if _scraper_lock.locked() and not force:
        skipped_report = {
            "status": "skipped",
            "reason": "scraper already running",
            "started_at": _iso(_utcnow()),
        }
        _scraper_runtime_state["last_report"] = skipped_report
        _scraper_runtime_state["last_status"] = "skipped"
        return skipped_report

    from app.models.opportunity import Opportunity
    from app.models.post import Post
    from app.models.user import User
    from app.services.ai_engine import ai_system

    async with _scraper_lock:
        started_at = _utcnow()
        _scraper_runtime_state["is_running"] = True
        _scraper_runtime_state["runs_total"] += 1
        _scraper_runtime_state["last_started_at"] = _iso(started_at)

        report_sources: list[dict[str, Any]] = []
        totals = {"fetched": 0, "inserted": 0, "updated": 0, "failed": 0, "deleted": 0}

        try:
            system_user = await User.find_one(User.is_admin == True)  # noqa: E712
            system_user_id = system_user.id if system_user else None

            print("[ScraperEngine] Running resilient live fetch for Ivy + core + extended opportunity platforms...")

            async def fetch_unstop_batch() -> tuple[list[dict], list[str]]:
                errors: list[str] = []
                tasks = [
                    asyncio.to_thread(
                        unstop_scraper.fetch_unstop_opportunities,
                        category,
                        max(10, settings.SCRAPER_UNSTOP_MAX_ITEMS // len(UNSTOP_CATEGORIES)),
                    )
                    for category in UNSTOP_CATEGORIES
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                opportunities: list[dict] = []
                for idx, result in enumerate(results):
                    if isinstance(result, Exception):
                        errors.append(f"{UNSTOP_CATEGORIES[idx]}: {result}")
                        continue
                    opportunities.extend(result)
                return (
                    _dedupe_by_url(opportunities)[: max(1, settings.SCRAPER_UNSTOP_MAX_ITEMS)],
                    errors,
                )

            base_fetch_results = await asyncio.gather(
                asyncio.to_thread(ivy_connector.fetch_ivy_league_opportunities, 10),
                fetch_unstop_batch(),
                asyncio.to_thread(
                    naukri_scraper.fetch_it_jobs,
                    max(1, settings.SCRAPER_NAUKRI_MAX_ITEMS),
                ),
                asyncio.to_thread(
                    internshala_scraper.fetch_live_opportunities,
                    max(1, settings.SCRAPER_INTERNSHALA_MAX_ITEMS),
                ),
                asyncio.to_thread(
                    hack2skill_scraper.fetch_live_opportunities,
                    max(1, settings.SCRAPER_HACK2SKILL_MAX_ITEMS),
                ),
                asyncio.to_thread(
                    freshersworld_scraper.fetch_live_opportunities,
                    max(1, settings.SCRAPER_FRESHERSWORLD_MAX_ITEMS),
                ),
                asyncio.to_thread(
                    indeed_india_scraper.fetch_live_opportunities,
                    max(1, settings.SCRAPER_INDEED_MAX_ITEMS),
                ),
                return_exceptions=True,
            )
            portal_specs: list[tuple[str, str]] = [
                (
                    str(config.get("source") or "").strip().lower(),
                    str(config.get("label") or config.get("source") or "Platform").strip(),
                )
                for config in GENERIC_PORTAL_LISTINGS
                if str(config.get("source") or "").strip()
            ]
            portal_fetch_results = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        generic_portal_scraper.fetch_live_opportunities,
                        source_name,
                        max(1, settings.SCRAPER_GENERIC_PORTAL_MAX_ITEMS),
                    )
                    for source_name, _ in portal_specs
                ],
                return_exceptions=True,
            )

            (
                ivy_result,
                unstop_result,
                naukri_result,
                internshala_result,
                hack2skill_result,
                freshersworld_result,
                indeed_india_result,
            ) = base_fetch_results

            async def _process_source_result(
                *,
                source_key: str,
                source_label: str,
                result: Any,
                empty_message: str | None = None,
                result_has_errors_tuple: bool = False,
            ) -> None:
                source_report = _new_source_report(source_key)
                try:
                    if isinstance(result, Exception):
                        raise result

                    source_errors: list[str] = []
                    opportunities = result
                    if result_has_errors_tuple:
                        opportunities, source_errors = result
                        source_report["errors"].extend(source_errors)

                    source_report["fetched"] = len(opportunities)
                    if source_report["fetched"] == 0 and not source_report["errors"] and empty_message:
                        source_report["errors"].append(empty_message)

                    insert_stats = await _insert_and_broadcast(
                        opportunities=opportunities,
                        source_name=source_label,
                        system_user_id=system_user_id,
                        ai_system=ai_system,
                        Opportunity=Opportunity,
                        Post=Post,
                    )
                    source_report.update(insert_stats)
                except Exception as exc:
                    source_report["errors"].append(str(exc))

                report_sources.append(source_report)

            await _process_source_result(
                source_key="ivy_rss",
                source_label="Ivy League Feed",
                result=ivy_result,
            )
            await _process_source_result(
                source_key="unstop",
                source_label="Unstop",
                result=unstop_result,
                empty_message="No opportunities parsed from Unstop.",
                result_has_errors_tuple=True,
            )
            await _process_source_result(
                source_key="naukri",
                source_label="Naukri",
                result=naukri_result,
                empty_message="No opportunities parsed from Naukri.",
            )
            await _process_source_result(
                source_key="internshala",
                source_label="Internshala",
                result=internshala_result,
                empty_message="No opportunities parsed from Internshala.",
            )
            await _process_source_result(
                source_key="hack2skill",
                source_label="Hack2Skill",
                result=hack2skill_result,
                empty_message="No opportunities parsed from Hack2Skill.",
            )
            await _process_source_result(
                source_key="freshersworld",
                source_label="Freshersworld",
                result=freshersworld_result,
                empty_message="No opportunities parsed from Freshersworld.",
            )
            await _process_source_result(
                source_key="indeed_india",
                source_label="Indeed India",
                result=indeed_india_result,
                empty_message="No opportunities parsed from Indeed India.",
            )

            for (source_name, source_label), source_result in zip(portal_specs, portal_fetch_results):
                await _process_source_result(
                    source_key=source_name,
                    source_label=source_label,
                    result=source_result,
                    empty_message=f"No opportunities parsed from {source_label}.",
                )

            cleanup_report = await _cleanup_inactive_opportunities(Opportunity)

            for source_report in report_sources:
                totals["fetched"] += int(source_report["fetched"])
                totals["inserted"] += int(source_report["inserted"])
                totals["updated"] += int(source_report["updated"])
                totals["failed"] += int(source_report["failed"])
            totals["deleted"] = int(cleanup_report["total_deleted"])

            any_errors = any(source_report["errors"] for source_report in report_sources)
            any_progress = (totals["fetched"] + totals["inserted"] + totals["updated"]) > 0
            if any_errors and not any_progress:
                status = "failed"
            elif any_errors:
                status = "partial_success"
            else:
                status = "success"

            finished_at = _utcnow()
            report = {
                "status": status,
                "started_at": _iso(started_at),
                "finished_at": _iso(finished_at),
                "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
                "totals": totals,
                "cleanup": cleanup_report,
                "sources": report_sources,
            }

            _scraper_runtime_state["last_finished_at"] = _iso(finished_at)
            _scraper_runtime_state["last_status"] = status
            _scraper_runtime_state["last_report"] = report
            if status in {"success", "partial_success"}:
                _scraper_runtime_state["last_successful_at"] = _iso(finished_at)
                _scraper_runtime_state["consecutive_failures"] = 0
            else:
                _scraper_runtime_state["consecutive_failures"] += 1

            print(
                f"[ScraperEngine] Completed ({status}) | "
                f"fetched={totals['fetched']} inserted={totals['inserted']} "
                f"updated={totals['updated']} deleted={totals['deleted']}"
            )
            return report
        finally:
            _scraper_runtime_state["is_running"] = False
