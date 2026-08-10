from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.time import utc_now

logger = logging.getLogger(__name__)

# Listing cards carry a title and a line of chrome; the role's actual
# requirements live on the detail page. Measured on the live corpus: only 47% of
# active rows had a description of any use, 44% were under 200 characters, and
# 140 were generator boilerplate ("Remote-friendly role indexed from ...").
MIN_USEFUL_DESCRIPTION_CHARS = 200

_TEMPLATE_DESCRIPTION = re.compile(
    r"(opportunity indexed from|indexed from|discovered on the official"
    r"|curated .{0,30}list entry|remote-friendly role indexed)",
    re.IGNORECASE,
)

# Page furniture that would otherwise dominate an extracted description.
_STRIP_SELECTORS = (
    "script", "style", "noscript", "nav", "header", "footer", "form",
    "aside", "svg", "button", "iframe",
)

# An error page still yields plenty of text. Without this guard a dead listing
# would have its description replaced by "Uh oh! Looks like you crashed..." plus
# the site's navigation - observed on a real Internshala 404 during testing.
_ERROR_PAGE_MARKERS = re.compile(
    r"(page (?:you are looking for )?(?:could not be found|does not exist|no longer exists)"
    r"|error 404|404 not found|looks like you crashed|this (?:job|internship|posting) "
    r"(?:is|has) (?:no longer|closed|expired|been removed)"
    r"|position (?:is )?(?:closed|filled|no longer available))",
    re.IGNORECASE,
)

_CONTENT_SELECTORS = (
    "[class*='job-description']",
    "[class*='jobDescription']",
    "[id*='job-description']",
    "[class*='description']",
    "[class*='posting']",
    "[data-testid*='description']",
    "article",
    "main",
)


@dataclass
class EnrichmentReport:
    scanned: int = 0
    attempted: int = 0
    improved: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "attempted": self.attempted,
            "improved": self.improved,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "errors": self.errors[:5],
        }


def needs_better_description(description: str | None) -> bool:
    text = str(description or "").strip()
    if len(text) < MIN_USEFUL_DESCRIPTION_CHARS:
        return True
    return bool(_TEMPLATE_DESCRIPTION.search(text))


def extract_description(html: str) -> str:
    """Pull the role description out of a detail page.

    Tries the containers ATS platforms actually use before falling back to the
    whole body, because a naive get_text() on a careers page returns the nav,
    the cookie banner and the footer ahead of anything about the job.
    """
    from app.services.scraper import _clean_description

    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_STRIP_SELECTORS)):
        tag.decompose()

    best = ""
    for selector in _CONTENT_SELECTORS:
        for node in soup.select(selector):
            candidate = _clean_description(str(node))
            if len(candidate) > len(best):
                best = candidate
        # Stop at the first selector that yields something substantial rather
        # than letting a broader one (main/article) overwrite a precise hit.
        if len(best) >= MIN_USEFUL_DESCRIPTION_CHARS:
            break

    if len(best) < MIN_USEFUL_DESCRIPTION_CHARS:
        body = _clean_description(str(soup.body or soup))
        if len(body) > len(best):
            best = body

    return best[: settings.DESCRIPTION_ENRICHMENT_MAX_CHARS]


def _interleave_by_host(rows: list) -> list:
    """Round-robin the candidates by hostname.

    Ordering strictly by recency groups every row from one source together, and
    a single bot-walled source then takes the whole run down with it: Indeed
    detail pages all answer 403, they were the newest rows, and four consecutive
    failures opened the fetch circuit breaker - so a 120-row pass enriched
    nothing at all. Interleaving means one dead host costs one failure per
    round instead of an unbroken run of them, and the breaker only opens if the
    failures are genuinely widespread.
    """
    from urllib.parse import urlparse

    buckets: dict[str, list] = {}
    for row in rows:
        host = urlparse(str(getattr(row, "url", "") or "")).hostname or "unknown"
        buckets.setdefault(host, []).append(row)
    ordered: list = []
    while buckets:
        for host in list(buckets):
            ordered.append(buckets[host].pop(0))
            if not buckets[host]:
                del buckets[host]
    return ordered


async def enrich_opportunity_descriptions(limit: int | None = None) -> dict[str, Any]:
    """Fetch detail pages for rows whose description is unusable.

    Deliberately budgeted and off the ingestion critical path: it re-fetches one
    page per opportunity, and the fetch chain may fall through to a paid
    provider. Newest rows first, so the feed a student sees today improves
    before the archive does.
    """
    from app.models.opportunity import Opportunity
    from app.services.scraper import _clean_description, _to_naive_utc
    from app.services.scraper_fetch_bridge import fetch_page

    report = EnrichmentReport()
    if not settings.DESCRIPTION_ENRICHMENT_ENABLED:
        return {**report.as_dict(), "status": "disabled"}

    budget = max(1, int(limit or settings.DESCRIPTION_ENRICHMENT_MAX_PER_RUN))
    # Over-fetch, since many candidates are filtered out in Python.
    candidates = (
        await Opportunity.find_many({"opportunity_status": "active"})
        .sort("-last_seen_at")
        .limit(budget * 5)
        .to_list()
    )
    candidates = _interleave_by_host(candidates)

    for opportunity in candidates:
        report.scanned += 1
        if report.attempted >= budget:
            break
        if not needs_better_description(getattr(opportunity, "description", "")):
            continue
        url = str(getattr(opportunity, "url", "") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue

        report.attempted += 1
        timeout = float(settings.DESCRIPTION_ENRICHMENT_TIMEOUT_SECONDS)
        try:
            page = await fetch_page(url, render=False, timeout_seconds=timeout)
        except Exception as exc:
            page = None
            first_error = f"{type(exc).__name__}"
        else:
            first_error = None

        # Escalate to the rendering chain when the cheap fetch was refused.
        # Indeed answers 403 to every detail page on a plain fetch, which is 129
        # of the rows still carrying a placeholder description - the largest
        # single group. The same URL returns 200 and a full page through
        # Obscura, so giving up at the first 403 was throwing away the only
        # descriptions those rows can ever have.
        blocked = page is None or getattr(page, "status_code", 0) in {401, 403, 405, 406, 408, 409, 425, 429} \
            or len(str(getattr(page, "text", "") or "").strip()) < 500
        if blocked:
            try:
                rendered = await fetch_page(url, render=True, timeout_seconds=max(timeout, 60.0))
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"{url}: {first_error or type(exc).__name__}")
                continue
            if rendered is not None and str(getattr(rendered, "text", "") or "").strip():
                page = rendered
        if page is None:
            report.failed += 1
            report.errors.append(f"{url}: {first_error or 'no_page'}")
            continue

        # A 404 body still yields plenty of extractable text, so status has to
        # be checked before content, not after.
        if int(getattr(page, "status_code", 0)) >= 400:
            report.failed += 1
            report.errors.append(f"{url}: HTTP {page.status_code}")
            continue

        extracted = extract_description(page.text or "")
        if _ERROR_PAGE_MARKERS.search(extracted):
            report.failed += 1
            report.errors.append(f"{url}: error_page_content")
            continue
        current = _clean_description(getattr(opportunity, "description", ""))
        # Only replace when the detail page is materially richer. A marginal
        # gain is not worth trading a source-provided summary for scraped chrome.
        if len(extracted) < MIN_USEFUL_DESCRIPTION_CHARS or len(extracted) <= len(current) * 1.2:
            report.unchanged += 1
            continue

        opportunity.description = extracted
        opportunity.updated_at = _to_naive_utc(utc_now())
        try:
            await opportunity.save()
            report.improved += 1
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"save {url}: {type(exc).__name__}")

    logger.info("description enrichment: %s", report.as_dict())
    return {**report.as_dict(), "status": "ok"}
