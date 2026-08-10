"""Reads the verified employer boards in company_board_registry.

Seven applicant tracking systems cover every board found, and all of them
publish JSON, so this needs no browser and no HTML parsing at scrape time. That
is the reason the discovery probe insisted on resolving employers to an API
wherever one existed: an API-backed board stays fresh for the cost of one
request, where a scraped page costs a fetch, a render and a parse that breaks
whenever the markup moves.

Boards are visited in a rotating window rather than all at once. Three hundred
and fifty-seven requests per run would dominate the batch budget and slow every
other source, while visiting only the first N would mean the tail never
refreshes. The window advances with the clock, so every board is reached within
a bounded number of runs and no board is permanently starved.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from typing import Any, Callable, Iterable

import requests

from app.core.config import settings
from app.services.company_board_registry import COMPANY_BOARDS, CompanyBoard

logger = logging.getLogger(__name__)


# What an employer calls a role aimed at a student or recent graduate. Used
# both to query the boards that support search and to select from those that
# do not.
EARLY_CAREER_TERMS = (
    "intern", "internship", "graduate", "new grad", "entry level", "entry-level",
    "junior", "trainee", "apprentice", "campus", "co-op", "coop", "fresher",
    "early career", "early-career", "student", "associate engineer",
    "trainee engineer", "analyst i", "rotational", "emerging talent",
)
# "internal", "international" and "internship manager" all contain "intern",
# and a "Senior Graduate Recruiter" hires graduates rather than being one.
_NOT_EARLY = (
    "internal", "international", "intern manager", "internship manager",
    "senior", "staff", "principal", "lead ", "head of", "director", "manager,",
    "vp ", "vice president", "architect",
)
# Levelled titles that mean 0-1 years without saying so: "Engineer I",
# "Software Engineer 1", "Associate Data Scientist". Roman numeral II and above
# is deliberately excluded.
_LEVEL_ONE = re.compile(
    r"\b(?:engineer|developer|analyst|scientist|designer|consultant|associate)\s*"
    r"(?:i|1)\b(?!\s*[iv])",
    re.I,
)


def board_source_key(company: str) -> str:
    """Per-employer source id, matching the existing company_* convention.

    The feed caps each source at two rows before pushing the rest into an
    overflow tail that falls past the row limit. Writing one shared
    "company_boards" label for all 357 employers therefore meant the entire
    registry competed for two slots: 44 scraped rows produced 2 visible ones and
    the other 42 were cut. One identity per employer is also what the feed's
    diversity rule is for - a hundred roles from one company should not crowd
    out every other employer.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    return f"company_{slug}" if slug else "company_boards"


def is_early_career_title(title: str) -> bool:
    lowered = f" {title.lower()} "
    if any(bad in lowered for bad in _NOT_EARLY):
        return False
    if any(term in lowered for term in EARLY_CAREER_TERMS):
        return True
    return bool(_LEVEL_ONE.search(title))


def _api_url(board: CompanyBoard) -> str | None:
    """Endpoint for a board, or None if the platform has no reader."""
    token = board.token
    if board.platform == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    if board.platform == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    if board.platform == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    if board.platform == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"
    if board.platform == "workable":
        return f"https://apply.workable.com/api/v1/widget/accounts/{token}"
    if board.platform == "recruitee":
        return f"https://{token}.recruitee.com/api/offers/"
    if board.platform == "eightfold":
        tenant = token.split(".")[0]
        return f"https://{token}/api/apply/v2/jobs?domain={tenant}.com&start=0&num=50"
    if board.platform == "custom":
        return token if token.startswith("http") else None
    if board.platform == "workday":
        parts = token.split("|")
        if len(parts) != 3:
            return None
        tenant, host, site = parts
        return f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    return None


def _rows(payload: Any, platform: str) -> list[dict[str, Any]]:
    """Pull the list of postings out of each platform's response shape."""
    if platform == "lever":
        return payload if isinstance(payload, list) else []
    if not isinstance(payload, dict):
        return []
    if platform == "smartrecruiters":
        return payload.get("content") or []
    if platform == "recruitee":
        return payload.get("offers") or []
    if platform == "workday":
        return payload.get("jobPostings") or []
    if platform == "eightfold" or platform == "custom":
        return payload.get("positions") or payload.get("jobs") or []
    return payload.get("jobs") or []


class CompanyBoardScraper:
    """Fetches a rotating slice of the verified employer boards each run."""

    def __init__(
        self,
        session: requests.Session | None = None,
        boards: Iterable[CompanyBoard] | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        from app.services.scraper import _build_retry_session

        self.session = session or _build_retry_session()
        self.boards = tuple(boards) if boards is not None else COMPANY_BOARDS
        self._clock = clock
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
        }

    def _window(self) -> list[CompanyBoard]:
        """The slice of boards due this run.

        Anchored to the clock rather than to a stored cursor so it survives
        restarts and needs no extra state: consecutive runs land on consecutive
        windows, and the whole registry is covered in a predictable cycle.
        """
        total = len(self.boards)
        size = max(1, int(settings.COMPANY_BOARDS_PER_RUN))
        if size >= total:
            return list(self.boards)
        bucket = int(self._clock() // max(60, int(settings.COMPANY_BOARDS_ROTATION_SECONDS)))
        start = (bucket * size) % total
        window = list(self.boards[start:start + size])
        if len(window) < size:  # wrapped past the end
            window += list(self.boards[: size - len(window)])
        return window

    def _parse(self, board: CompanyBoard, row: dict[str, Any]) -> dict[str, Any] | None:
        from app.services.scraper import (
            _canonicalize_url, _collapse_whitespace, _parse_datetime, _strip_html,
        )

        platform = board.platform
        title = ""
        url = ""
        location = ""
        description = ""
        posted = None

        if platform == "greenhouse":
            title = str(row.get("title") or "")
            url = str(row.get("absolute_url") or "")
            loc = row.get("location")
            location = str(loc.get("name") or "") if isinstance(loc, dict) else str(loc or "")
            description = _strip_html(str(row.get("content") or ""))
            posted = _parse_datetime(str(row.get("updated_at") or ""))
        elif platform == "lever":
            title = str(row.get("text") or "")
            url = str(row.get("hostedUrl") or row.get("applyUrl") or "")
            cats = row.get("categories") or {}
            location = str(cats.get("location") or "") if isinstance(cats, dict) else ""
            description = _strip_html(str(row.get("descriptionPlain") or row.get("description") or ""))
        elif platform == "ashby":
            title = str(row.get("title") or "")
            url = str(row.get("jobUrl") or row.get("applyUrl") or "")
            location = str(row.get("location") or "")
            description = _strip_html(str(row.get("descriptionPlain") or row.get("descriptionHtml") or ""))
            posted = _parse_datetime(str(row.get("publishedAt") or ""))
        elif platform == "smartrecruiters":
            title = str(row.get("name") or "")
            job_id = str(row.get("id") or "")
            url = f"https://jobs.smartrecruiters.com/{board.token}/{job_id}" if job_id else ""
            loc = row.get("location") or {}
            location = ", ".join(
                str(loc.get(k)) for k in ("city", "country") if isinstance(loc, dict) and loc.get(k)
            )
            posted = _parse_datetime(str(row.get("releasedDate") or ""))
        elif platform == "workable":
            title = str(row.get("title") or "")
            url = str(row.get("url") or row.get("application_url") or "")
            location = str(row.get("location") or "")
        elif platform == "recruitee":
            title = str(row.get("title") or "")
            url = str(row.get("careers_url") or row.get("careers_apply_url") or "")
            location = str(row.get("location") or "")
            description = _strip_html(str(row.get("description") or ""))
        elif platform == "workday":
            title = str(row.get("title") or "")
            path = str(row.get("externalPath") or "")
            tenant, host, site = (board.token.split("|") + ["", ""])[:3]
            url = f"https://{tenant}.{host}.myworkdayjobs.com/en-US/{site}{path}" if path else ""
            location = str(row.get("locationsText") or "")
        else:  # eightfold and custom share a shape
            title = str(row.get("name") or row.get("title") or "")
            url = str(row.get("canonicalPositionUrl") or row.get("job_link") or row.get("url") or "")
            location = str(row.get("location") or "")
            description = _strip_html(str(row.get("job_description") or row.get("description") or ""))

        title = _collapse_whitespace(title)
        url = _canonicalize_url(url)
        if not title or not url:
            return None

        location = _collapse_whitespace(location)
        bits = [description, f"Location: {location}." if location else ""]
        text = _collapse_whitespace(" ".join(b for b in bits if b))

        # Classify from the title and the employer context, never the body: a
        # job description that happens to mention a hackathon is still a job,
        # and a mistyped row bypasses the early-career filter downstream.
        lowered = title.lower()
        if "intern" in lowered and "internal" not in lowered:
            opportunity_type = "Internship"
        elif any(word in lowered for word in ("apprentice", "trainee", "graduate program")):
            opportunity_type = "Internship"
        else:
            opportunity_type = "Job"

        return {
            "title": title[:220],
            "description": (text or f"{opportunity_type} at {board.company}.")[:700],
            "url": url,
            "opportunity_type": opportunity_type,
            "university": board.company,
            "location": location or None,
            "deadline": posted + timedelta(days=45) if posted else None,
            "source": board_source_key(board.company),
        }

    def fetch_live_opportunities(self, max_items: int = 400) -> tuple[list[dict], list[str]]:
        from app.services.scraper import _dedupe_by_url

        opportunities: list[dict] = []
        errors: list[str] = []
        window = self._window()
        per_board = max(1, max_items // max(1, len(window)) + 1)

        for board in window:
            if len(opportunities) >= max_items:
                break
            url = _api_url(board)
            if not url:
                errors.append(f"{board.company}: no reader for platform {board.platform}")
                continue
            try:
                if board.platform == "workday":
                    # Workday filters server-side, so ask it for early-career
                    # roles rather than pulling the first twenty of several
                    # thousand and discarding them. On boards this size the top
                    # of the list is almost entirely senior: an unfiltered run
                    # over 60 boards yielded 121 postings of which one was for a
                    # student.
                    response = self.session.post(
                        url,
                        json={
                            "appliedFacets": {},
                            "limit": 20,
                            "offset": 0,
                            "searchText": settings.COMPANY_BOARDS_SEARCH_TEXT,
                        },
                        headers=self.headers,
                        timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                    )
                else:
                    response = self.session.get(
                        url, headers=self.headers, timeout=settings.SCRAPER_TIMEOUT_SECONDS
                    )
                response.raise_for_status()
                rows = _rows(response.json(), board.platform)
            except Exception as exc:
                errors.append(f"{board.company}: {type(exc).__name__}: {exc}"[:160])
                continue

            # Boards with no server-side filter are scanned in full and
            # selected by title, because the early-career roles are scattered
            # through the list rather than at the top of it.
            kept_here = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                parsed = self._parse(board, row)
                if not parsed:
                    continue
                if settings.COMPANY_BOARDS_EARLY_CAREER_ONLY and not is_early_career_title(
                    parsed["title"]
                ):
                    continue
                opportunities.append(parsed)
                kept_here += 1
                if kept_here >= per_board or len(opportunities) >= max_items:
                    break

        if errors and not opportunities:
            raise RuntimeError("; ".join(errors[:5]))
        return _dedupe_by_url(opportunities)[:max_items], errors


company_board_scraper = CompanyBoardScraper()
