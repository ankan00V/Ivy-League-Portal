from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, TypeAlias
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
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

OpportunityDict: TypeAlias = dict[str, Any]


@dataclass
class ParseResult:
    item: OpportunityDict | None
    confidence: float
    missing_fields: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


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

GREENHOUSE_DEFAULT_BOARD_TOKENS = ["databricks", "stripe", "airbnb"]

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
        "source": "major_league_hacking",
        "label": "Major League Hacking",
        "default_type": "Hackathon",
        "default_university": "Major League Hacking",
        "listings": [
            "https://mlh.io/seasons/2026/events",
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
        "source": "naukri",
        "label": "Naukri",
        "default_type": "Job",
        "default_university": "Naukri Recruiters",
        "listings": [
            "https://www.naukri.com/internship-jobs",
            "https://www.naukri.com/fresher-jobs",
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
        "source": "instahyre",
        "label": "Instahyre",
        "default_type": "Job",
        "default_university": "Instahyre Recruiters",
        "listings": [
            "https://www.instahyre.com/candidate/opportunities/",
        ],
    },
    {
        "source": "hirist",
        "label": "Hirist",
        "default_type": "Job",
        "default_university": "Hirist",
        "listings": [
            "https://www.hirist.tech/",
        ],
    },
    {
        "source": "cuvette",
        "label": "Cuvette",
        "default_type": "Internship",
        "default_university": "Cuvette",
        "listings": [
            "https://www.cuvette.tech/jobs",
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
        "enabled": False,
        "disabled_reason": "Current public internship page exposes category navigation in bounded checks, not direct opportunity listings; requires a dedicated connector.",
        "listings": [
            "https://www.wayup.com/s/internships/",
        ],
    },
    {
        "source": "chegg_internships",
        "label": "Chegg Internships",
        "default_type": "Internship",
        "default_university": "Chegg",
        "enabled": False,
        "disabled_reason": "Chegg's official internships page says Internships.com and careermatch.com closed in December 2023.",
        "listings": [
            "https://www.chegg.com/skills/internships-announcement/",
        ],
    },
    {
        "source": "zintellect",
        "label": "Zintellect",
        "default_type": "Internship",
        "default_university": "Zintellect",
        "enabled": False,
        "disabled_reason": "Current public catalog renders an app shell/catalog entry in bounded checks; requires a dedicated catalog API/browser connector.",
        "listings": [
            "https://www.zintellect.com/catalog",
        ],
    },
    {
        "source": "interstride",
        "label": "Interstride",
        "default_type": "Internship",
        "default_university": "Interstride",
        "enabled": False,
        "disabled_reason": "Student/job portal access is institution/account gated; use an approved partner connector instead of anonymous scraping.",
        "listings": [
            "https://www.interstride.com/students/",
        ],
    },
    {
        "source": "untapped",
        "label": "Untapped",
        "default_type": "Internship",
        "default_university": "Untapped",
        "enabled": False,
        "disabled_reason": "Current public page redirects to a career-program marketing page in bounded checks, not direct opportunity listings.",
        "listings": [
            "https://www.untapped.io/",
        ],
    },
    {
        "source": "parker_dewey",
        "label": "Parker Dewey",
        "default_type": "Internship",
        "default_university": "Parker Dewey",
        "enabled": False,
        "disabled_reason": "Current public career-launchers page exposes marketing/navigation links in bounded checks; use an approved micro-internship connector.",
        "listings": [
            "https://www.parkerdewey.com/career-launchers",
        ],
    },
    {
        "source": "extern",
        "label": "Extern",
        "default_type": "Internship",
        "default_university": "Extern",
        "listings": [
            "https://www.extern.com/externships",
        ],
    },
    {
        "source": "github_internship_lists",
        "label": "GitHub Internship Lists",
        "default_type": "Internship",
        "default_university": "GitHub Curated Lists",
        "listings": [
            "https://github.com/SimplifyJobs/Summer2026-Internships",
            "https://github.com/SimplifyJobs/New-Grad-Positions",
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
    {
        "source": "toptal",
        "label": "Toptal",
        "default_type": "Job",
        "default_university": "Toptal",
        "enabled": False,
        "disabled_reason": "No stable public early-career job feed; homepage is marketing content.",
        "listings": [
            "https://www.toptal.com/",
        ],
    },
    {
        "source": "skip_the_drive",
        "label": "Skip The Drive",
        "default_type": "Job",
        "default_university": "Skip The Drive",
        "listings": [
            "https://www.skipthedrive.com/",
        ],
    },
    {
        "source": "nodesk",
        "label": "NoDesk",
        "default_type": "Job",
        "default_university": "NoDesk",
        "listings": [
            "https://nodesk.co/remote-jobs/",
        ],
    },
    {
        "source": "remote_habits",
        "label": "RemoteHabits",
        "default_type": "Job",
        "default_university": "RemoteHabits",
        "listings": [
            "https://remotehabits.com/jobs/",
        ],
    },
    {
        "source": "remotive",
        "label": "Remotive",
        "default_type": "Job",
        "default_university": "Remotive",
        "listings": [
            "https://remotive.com/api/remote-jobs",
        ],
    },
    {
        "source": "remote4me",
        "label": "Remote4Me",
        "default_type": "Job",
        "default_university": "Remote4Me",
        "listings": [
            "https://remote4me.com/",
        ],
    },
    {
        "source": "pangian",
        "label": "Pangian",
        "default_type": "Job",
        "default_university": "Pangian",
        "enabled": False,
        "disabled_reason": "Public job board is currently in transition and the previous listings URL returns 404.",
        "listings": [
            "https://pangian.com/job-travel-remote/",
        ],
    },
    {
        "source": "remotees",
        "label": "Remotees",
        "default_type": "Job",
        "default_university": "Remotees",
        "listings": [
            "https://remotees.com/",
        ],
    },
    {
        "source": "justremote",
        "label": "JustRemote",
        "default_type": "Job",
        "default_university": "JustRemote",
        "listings": [
            "https://justremote.co/remote-jobs",
        ],
    },
    {
        "source": "remotecrew",
        "label": "Remotecrew",
        "default_type": "Job",
        "default_university": "Remotecrew",
        "enabled": False,
        "disabled_reason": "Homepage is a hiring-service marketing site, not a public student job feed.",
        "listings": [
            "https://remotecrew.io/",
        ],
    },
    {
        "source": "europe_remotely",
        "label": "Europe Remotely",
        "default_type": "Job",
        "default_university": "Europe Remotely",
        "enabled": False,
        "disabled_reason": "Blocks anonymous scraper traffic with 403.",
        "listings": [
            "https://europeremotely.com/",
        ],
    },
    {
        "source": "remoteok_europe",
        "label": "Remote OK Europe",
        "default_type": "Job",
        "default_university": "Remote OK",
        "listings": [
            "https://remoteok.com/api",
        ],
    },
    {
        "source": "remoteok_asia",
        "label": "Remote OK Asia",
        "default_type": "Job",
        "default_university": "Remote OK",
        "listings": [
            "https://remoteok.com/api",
        ],
    },
    {
        "source": "flexjobs",
        "label": "FlexJobs",
        "default_type": "Job",
        "default_university": "FlexJobs",
        "enabled": False,
        "disabled_reason": "Public site repeatedly times out/blocks anonymous scraping; requires a dedicated approved integration.",
        "listings": [
            "https://www.flexjobs.com/",
        ],
    },
    {
        "source": "remote_co",
        "label": "Remote.co",
        "default_type": "Job",
        "default_university": "Remote.co",
        "enabled": False,
        "disabled_reason": "Public listings repeatedly time out during bounded health checks; requires a dedicated approved integration.",
        "listings": [
            "https://remote.co/remote-jobs/",
        ],
    },
    {
        "source": "we_work_remotely",
        "label": "We Work Remotely",
        "default_type": "Job",
        "default_university": "We Work Remotely",
        "listings": [
            "https://weworkremotely.com/remote-jobs.rss",
        ],
    },
    {
        "source": "remoteok",
        "label": "Remote OK",
        "default_type": "Job",
        "default_university": "Remote OK",
        "listings": [
            "https://remoteok.com/api",
        ],
    },
    {
        "source": "angellist",
        "label": "AngelList",
        "default_type": "Job",
        "default_university": "AngelList Startups",
        "enabled": False,
        "disabled_reason": "AngelList jobs redirects to Wellfound and blocks anonymous scraping; Wellfound is already tracked separately.",
        "listings": [
            "https://angel.co/jobs",
        ],
    },
    {
        "source": "linkedin_remote",
        "label": "LinkedIn Remote Jobs",
        "default_type": "Job",
        "default_university": "LinkedIn",
        "listings": [
            "https://www.linkedin.com/jobs/search/?keywords=remote&location=Worldwide",
        ],
    },
    {
        "source": "freelancer",
        "label": "Freelancer",
        "default_type": "Job",
        "default_university": "Freelancer",
        "listings": [
            "https://www.freelancer.com/jobs",
        ],
    },
    {
        "source": "working_nomads",
        "label": "Working Nomads",
        "default_type": "Job",
        "default_university": "Working Nomads",
        "listings": [
            "https://www.workingnomads.com/jobs",
        ],
    },
    {
        "source": "simplyhired",
        "label": "SimplyHired",
        "default_type": "Job",
        "default_university": "SimplyHired",
        "listings": [
            "https://www.simplyhired.com/search?q=remote",
        ],
    },
    {
        "source": "jobspresso",
        "label": "Jobspresso",
        "default_type": "Job",
        "default_university": "Jobspresso",
        "listings": [
            "https://jobspresso.co/remote-work/",
        ],
    },
    {
        "source": "virtual_vocations",
        "label": "Virtual Vocations",
        "default_type": "Job",
        "default_university": "Virtual Vocations",
        "listings": [
            "https://www.virtualvocations.com/jobs",
        ],
    },
    {
        "source": "stackoverflow_jobs",
        "label": "Stack Overflow Jobs",
        "default_type": "Job",
        "default_university": "Stack Overflow",
        "enabled": False,
        "disabled_reason": "Stack Overflow Jobs is not a stable globally available public listings source.",
        "listings": [
            "https://stackoverflow.com/jobs",
        ],
    },
    {
        "source": "glassdoor_remote",
        "label": "Glassdoor Remote",
        "default_type": "Job",
        "default_university": "Glassdoor",
        "enabled": False,
        "disabled_reason": "Glassdoor blocks anonymous scraping with 403.",
        "listings": [
            "https://www.glassdoor.com/Job/remote-jobs-SRCH_KO0,6.htm",
        ],
    },
    {
        "source": "monster",
        "label": "Monster",
        "default_type": "Job",
        "default_university": "Monster",
        "listings": [
            "https://www.monster.com/jobs/search?q=remote",
        ],
    },
    {
        "source": "careercloud",
        "label": "Careercloud",
        "default_type": "Job",
        "default_university": "Careercloud",
        "enabled": False,
        "disabled_reason": "Career advice/aggregation site, not a stable direct opportunity feed.",
        "listings": [
            "https://www.careercloud.com/",
        ],
    },
    {
        "source": "careerbuilder",
        "label": "CareerBuilder",
        "default_type": "Job",
        "default_university": "CareerBuilder",
        "listings": [
            "https://www.careerbuilder.com/jobs?keywords=remote",
        ],
    },
    {
        "source": "careeronestop",
        "label": "CareerOneStop",
        "default_type": "Job",
        "default_university": "CareerOneStop",
        "enabled": False,
        "disabled_reason": "Blocks anonymous scraper traffic with 403 and is not student-specific.",
        "listings": [
            "https://www.careeronestop.org/",
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
    "browse all jobs",
    "career center",
    "employers",
    "employers / post job",
    "get free job alerts",
    "job alerts",
    "job application tracking",
    "post a job",
    "resume review",
    "student career center",
}

EARLY_CAREER_PATTERNS = [
    r"\bintern(?:ship)?s?\b",
    r"\bentry[-\s]?level\b",
    r"\bjunior\b",
    r"\bfreshers?\b",
    r"\bnew\s+grads?\b",
    r"\brecent\s+graduates?\b",
    r"\bgraduate\s+(?:role|program|programme|scheme|trainee)\b",
    r"\btrainees?\b",
    r"\bapprentices?(?:hip)?\b",
    r"\bno\s+(?:prior\s+)?experience\b",
    r"\b0\s*(?:-|–|to)\s*1\s+years?\b",
    r"\b(?:up\s+to|maximum|max\.?)\s+1\s+year\b",
    r"\b(?:experience|exp)\s*[:\-]?\s*0\s*(?:-|–|to)\s*1\b",
]

EXPERIENCED_ROLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bhead\s+of\b",
    r"\barchitect\b",
    r"\b[2-9]\+?\s+years?\b",
    r"\b(?:minimum|min\.?|at\s+least)\s+[2-9]\s+years?\b",
    r"\b[2-9]\s*(?:-|–|to)\s*\d+\s+years?\b",
    r"\bbootcamp\b",
    r"\bjob\s+guaranteed\b",
    r"\bpaid\s+training\b",
]

TRACKING_QUERY_KEYS = {
    "_hsenc",
    "_hsmi",
    "campaignid",
    "clickid",
    "fbclid",
    "gclid",
    "gh_jid",
    "igshid",
    "li_fat_id",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "msclkid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "refs",
    "source",
    "src",
    "trk",
    "trkinfo",
    "tracking",
    "trackingid",
    "session",
    "sessionid",
}

ORGANIZATION_SUFFIX_TOKENS = {
    "inc",
    "llc",
    "ltd",
    "limited",
    "pvt",
    "private",
    "corp",
    "corporation",
    "company",
    "co",
    "technologies",
    "technology",
    "solutions",
}

TITLE_NOISE_TOKENS = {
    "job",
    "jobs",
    "opening",
    "openings",
    "role",
    "hiring",
    "opportunity",
    "internship",
    "internships",
}

WORK_MODE_PATTERNS: list[tuple[str, list[str]]] = [
    ("Remote", [r"\bremote\b", r"\bwork from home\b", r"\bwfh\b"]),
    ("Hybrid", [r"\bhybrid\b"]),
    ("Onsite", [r"\bon[-\s]?site\b", r"\bin office\b"]),
]

STIPEND_PATTERNS = [
    r"\b(?:stipend|salary|ctc|pay)\s*[:\-]?\s*((?:rs\.?|inr|₹)\s*[\d,]+(?:\s*-\s*(?:rs\.?|inr|₹)?\s*[\d,]+)?(?:\s*/\s*(?:month|week|year|annum))?)",
    r"\b((?:rs\.?|inr|₹)\s*[\d,]+(?:\s*-\s*(?:rs\.?|inr|₹)?\s*[\d,]+)?(?:\s*/\s*(?:month|week|year|annum)))",
]

BATCH_PATTERNS = [
    r"\b(20\d{2})\s*(?:,|/|or|and|-|to)\s*(20\d{2})\b",
    r"\bbatch(?:es)?\s*(?:of)?\s*(20\d{2}(?:\s*(?:,|/|or|and)\s*20\d{2})*)\b",
]

PARSE_COMPLETENESS_FIELDS = [
    "title",
    "company",
    "location",
    "work_mode",
    "stipend",
    "duration",
    "eligibility",
    "apply_url",
    "deadline",
    "posted_date",
    "description",
    "tags",
    "source_id",
]

FIELD_ALIASES = {
    "company": "university",
    "apply_url": "url",
    "posted_date": "created_at",
    "duration": "duration_months",
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


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    value = str(value).strip()
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


def _hash_key(value: str | None) -> str:
    normalized = _collapse_whitespace(value).lower()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _query_key_is_tracking(key: str) -> bool:
    normalized = key.strip().lower()
    return (
        normalized in TRACKING_QUERY_KEYS
        or normalized.startswith("utm_")
        or normalized.endswith("_session_id")
        or normalized.endswith("_tracking_id")
    )


def _canonicalize_url(value: str | None) -> str:
    url = (value or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() or "https"
        host = (parsed.netloc or "").lower()
        path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"

        if "linkedin.com" in host:
            job_id = ""
            patterns = [
                r"/jobs/view/(\d+)",
                r"/jobs/view/[^/?#]*?(\d{6,})(?:$|[/?#])",
            ]
            for pattern in patterns:
                match = re.search(pattern, f"{path}/")
                if match:
                    job_id = match.group(1)
                    break
            if not job_id:
                query_values = dict(parse_qsl(parsed.query, keep_blank_values=False))
                job_id = query_values.get("currentJobId") or query_values.get("jobId") or ""
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}"

        if "internshala.com" in host:
            normalized_path = path.strip("/")
            slug = ""
            detail_match = re.search(r"(?:internship/detail|internships?/detail)/([^/?#]+)", normalized_path)
            internship_match = re.search(r"(?:internship|internships)/([^/?#]+)", normalized_path)
            if detail_match:
                slug = detail_match.group(1)
            elif internship_match:
                slug = internship_match.group(1)
            if slug:
                return f"https://internshala.com/internship/{slug.strip('/')}"

        filtered_query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=False)
            if not _query_key_is_tracking(key)
        ]
        query = urlencode(filtered_query, doseq=True)
        return urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return url


def canonicalize_apply_url(value: str | None) -> str:
    return _canonicalize_url(value)


def is_valid_apply_url(value: str | None) -> bool:
    return str(value or "").strip().lower().startswith(("http://", "https://"))


def _record_value(record: dict[str, Any], field_name: str) -> Any:
    if field_name in record:
        return record.get(field_name)
    alias = FIELD_ALIASES.get(field_name)
    if alias:
        return record.get(alias)
    return None


def _missing_parse_fields(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field_name in PARSE_COMPLETENESS_FIELDS:
        value = _record_value(record, field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not _collapse_whitespace(value):
            missing.append(field_name)
            continue
        if isinstance(value, list) and not value:
            missing.append(field_name)
    return missing


def _parse_confidence(record: dict[str, Any], missing_fields: list[str]) -> float:
    total = max(1, len(PARSE_COMPLETENESS_FIELDS))
    completeness = (total - len(missing_fields)) / total
    if not str(record.get("url") or "").startswith(("http://", "https://")):
        completeness -= 0.15
    if len(_collapse_whitespace(record.get("description"))) < 40:
        completeness -= 0.10
    return round(max(0.0, min(1.0, completeness)), 3)


def parse_result_from_record(record: dict[str, Any] | None, parse_errors: list[str] | None = None) -> ParseResult:
    errors = [str(item) for item in list(parse_errors or []) if str(item).strip()]
    if not record:
        return ParseResult(item=None, confidence=0.0, missing_fields=list(PARSE_COMPLETENESS_FIELDS), parse_errors=errors)
    enriched = _enrich_metadata(dict(record))
    missing_fields = _missing_parse_fields(enriched)
    return ParseResult(
        item=enriched,
        confidence=_parse_confidence(enriched, missing_fields),
        missing_fields=missing_fields,
        parse_errors=errors,
    )


def parse_results_from_records(records: Iterable[dict[str, Any]]) -> list[ParseResult]:
    return [parse_result_from_record(record) for record in _dedupe_by_url(records)]


def _slugify_text(value: str | None) -> str:
    text = _collapse_whitespace(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _normalize_organization_name(value: str | None) -> str:
    text = _collapse_whitespace(value).lower()
    if not text:
        return ""
    tokens = [token for token in re.split(r"[^a-z0-9]+", text) if token]
    filtered = [token for token in tokens if token not in ORGANIZATION_SUFFIX_TOKENS]
    return "-".join(filtered[:8]).strip("-")


def _normalize_opportunity_title(value: str | None) -> str:
    text = _collapse_whitespace(value).lower()
    if not text:
        return ""
    text = re.sub(r"\((?:remote|hybrid|onsite|on-site)[^)]*\)", " ", text)
    text = re.sub(r"\b(?:full[-\s]?time|part[-\s]?time|internship|intern|job)\b", " ", text)
    tokens = [token for token in re.split(r"[^a-z0-9+#]+", text) if token]
    filtered = [token for token in tokens if token not in TITLE_NOISE_TOKENS]
    return "-".join(filtered[:12]).strip("-")


def _duplicate_cluster_key(record: dict[str, Any]) -> str:
    organization = str(record.get("normalized_organization") or "").strip()
    title = str(record.get("normalized_title") or "").strip()
    opportunity_type = _slugify_text(record.get("opportunity_type"))
    location = _slugify_text(record.get("location"))
    return "::".join(part for part in [organization, title, opportunity_type, location] if part)


def _canonical_key(record: dict[str, Any]) -> str:
    title = str(record.get("normalized_title") or _normalize_opportunity_title(record.get("title")))
    organization = str(record.get("normalized_organization") or _normalize_organization_name(record.get("university")))
    opportunity_type = _slugify_text(record.get("opportunity_type"))
    work_mode = _slugify_text(record.get("work_mode"))
    return "::".join(part for part in [organization, title, opportunity_type, work_mode] if part)


def _extract_work_mode(text: str) -> str | None:
    haystack = _collapse_whitespace(text).lower()
    if not haystack:
        return None
    for label, patterns in WORK_MODE_PATTERNS:
        if any(re.search(pattern, haystack, re.IGNORECASE) for pattern in patterns):
            return label
    return None


def _extract_stipend(text: str) -> str | None:
    haystack = _collapse_whitespace(text)
    for pattern in STIPEND_PATTERNS:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            return _collapse_whitespace(match.group(1))[:80]
    return None


def _extract_batch_years(text: str) -> list[int]:
    haystack = _collapse_whitespace(text)
    years: set[int] = set()
    for pattern in BATCH_PATTERNS:
        for match in re.finditer(pattern, haystack, re.IGNORECASE):
            for group in match.groups():
                if not group:
                    continue
                for candidate in re.findall(r"20\d{2}", str(group)):
                    years.add(int(candidate))
    if not years and re.search(r"\bbatch(?:es)?\b", haystack, re.IGNORECASE):
        for candidate in re.findall(r"20\d{2}", haystack):
            years.add(int(candidate))
    return sorted(year for year in years if 2020 <= year <= 2035)


def _extract_eligibility(text: str) -> str | None:
    haystack = _collapse_whitespace(text)
    if not haystack:
        return None
    patterns = [
        r"\b(?:eligibility|eligible|who can apply)\s*[:\-]?\s*([^.;]{12,160})",
        r"\b(?:students?|candidates?)\s+(?:from|of)\s+([^.;]{12,140})",
    ]
    for pattern in patterns:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match:
            return _collapse_whitespace(match.group(1))[:160]
    return None


def _extract_location(text: str) -> str | None:
    haystack = _collapse_whitespace(text)
    if not haystack:
        return None
    match = re.search(
        r"\b(?:location|job location|based in)\s*[:\-]?\s*([A-Za-z][A-Za-z0-9 ,/&-]{2,80})",
        haystack,
        re.IGNORECASE,
    )
    if match:
        return _collapse_whitespace(match.group(1))[:80]
    return None


def _extract_ppo_availability(text: str) -> str | None:
    haystack = _collapse_whitespace(text).lower()
    if "ppo" in haystack:
        if re.search(r"\bppo\b.*\b(?:available|offered|opportunity)\b", haystack):
            return "Available"
        if re.search(r"\bno\b.*\bppo\b|\bppo\b.*\bnot\b", haystack):
            return "Not Available"
        return "Possible"
    return None


def _enrich_metadata(record: dict[str, Any]) -> dict[str, Any]:
    description = _collapse_whitespace(record.get("description"))
    title = _collapse_whitespace(record.get("title"))
    university = _collapse_whitespace(record.get("university"))
    metadata_text = " ".join(part for part in [title, description, university] if part)
    enriched = dict(record)
    enriched["url"] = _canonicalize_url(record.get("url"))
    enriched["location"] = record.get("location") or _extract_location(metadata_text)
    enriched["work_mode"] = record.get("work_mode") or _extract_work_mode(metadata_text)
    enriched["stipend"] = record.get("stipend") or _extract_stipend(metadata_text)
    enriched["eligibility"] = record.get("eligibility") or _extract_eligibility(metadata_text)
    enriched["batch_years"] = list(record.get("batch_years") or _extract_batch_years(metadata_text))
    enriched["ppo_available"] = record.get("ppo_available") or _extract_ppo_availability(metadata_text)
    enriched["normalized_title"] = record.get("normalized_title") or _normalize_opportunity_title(title)
    enriched["normalized_organization"] = record.get("normalized_organization") or _normalize_organization_name(university)
    enriched["canonical_key"] = record.get("canonical_key") or _canonical_key(enriched)
    enriched["canonical_url_hash"] = record.get("canonical_url_hash") or _hash_key(enriched.get("url"))
    source_name = _collapse_whitespace(record.get("source")).lower()
    source_id_text = _collapse_whitespace(record.get("source_id")) or _collapse_whitespace(enriched.get("url"))
    enriched["source_id"] = record.get("source_id") or _hash_key(f"{source_name}:{source_id_text}")[:24]
    tcl_parts = [
        _normalize_organization_name(university),
        _normalize_opportunity_title(title),
        _slugify_text(enriched.get("location")),
    ]
    enriched["title_company_location_hash"] = record.get("title_company_location_hash") or _hash_key(
        "::".join(part for part in tcl_parts if part)
    )
    enriched["duplicate_cluster_key"] = record.get("duplicate_cluster_key") or _duplicate_cluster_key(enriched)
    return enriched


def _dedupe_by_url(records: Iterable[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    seen_keys: set[str] = set()
    seen_clusters: set[str] = set()
    deduped: list[dict] = []
    for record in records:
        enriched = _enrich_metadata(record)
        url = (enriched.get("url") or "").strip()
        canonical_key = str(enriched.get("canonical_key") or "").strip()
        duplicate_cluster_key = str(enriched.get("duplicate_cluster_key") or "").strip()
        if not url:
            continue
        if url in seen_urls or (canonical_key and canonical_key in seen_keys) or (
            duplicate_cluster_key and duplicate_cluster_key in seen_clusters
        ):
            continue
        seen_urls.add(url)
        if canonical_key:
            seen_keys.add(canonical_key)
        if duplicate_cluster_key:
            seen_clusters.add(duplicate_cluster_key)
        deduped.append(enriched)
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
    current_time = _to_naive_utc(now or utc_now())
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


def is_early_career_opportunity(record: dict[str, Any]) -> bool:
    opportunity_type = _collapse_whitespace(record.get("opportunity_type")).lower()
    if opportunity_type != "job":
        return True

    primary_signal_parts: list[str] = []
    tags_signal_parts: list[str] = []
    for field in ("title", "eligibility"):
        value = record.get(field)
        if isinstance(value, (list, tuple, set)):
            primary_signal_parts.append(" ".join(str(item) for item in value))
        else:
            primary_signal_parts.append(str(value or ""))

    value = record.get("tags")
    if isinstance(value, (list, tuple, set)):
        tags_signal_parts.append(" ".join(str(item) for item in value))
    else:
        tags_signal_parts.append(str(value or ""))

    primary_text = _collapse_whitespace(" ".join(primary_signal_parts)).lower()
    tags_text = _collapse_whitespace(" ".join(tags_signal_parts)).lower()
    description_text = _collapse_whitespace(record.get("description")).lower()
    text = _collapse_whitespace(f"{primary_text} {tags_text} {description_text}").lower()
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in EXPERIENCED_ROLE_PATTERNS):
        return False
    if any(re.search(pattern, primary_text, re.IGNORECASE) for pattern in EARLY_CAREER_PATTERNS):
        return True
    tags = {tag.strip().lower() for tag in re.split(r"[,|]", tags_text) if tag.strip()}
    return bool(tags & {"intern", "internship", "entry level", "entry-level", "new grad", "graduate trainee"})


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


class GreenhouseScraper:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or _build_retry_session()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        }

    def _configured_board_tokens(self) -> list[str]:
        raw_value = (settings.SCRAPER_GREENHOUSE_BOARD_TOKENS or "").strip()
        if not raw_value:
            return list(GREENHOUSE_DEFAULT_BOARD_TOKENS)
        tokens: list[str] = []
        for token in re.split(r"[\s,]+", raw_value):
            normalized = token.strip().strip("/").lower()
            if normalized and normalized not in tokens:
                tokens.append(normalized)
        return tokens or list(GREENHOUSE_DEFAULT_BOARD_TOKENS)

    def _job_location(self, job: dict[str, Any]) -> str | None:
        location = job.get("location")
        if isinstance(location, dict):
            value = _collapse_whitespace(str(location.get("name") or ""))
            return value or None
        if isinstance(location, str):
            value = _collapse_whitespace(location)
            return value or None
        return None

    def _job_department(self, job: dict[str, Any]) -> str | None:
        departments = job.get("departments")
        if not isinstance(departments, list):
            return None
        names = [
            _collapse_whitespace(str(item.get("name") or ""))
            for item in departments
            if isinstance(item, dict) and _collapse_whitespace(str(item.get("name") or ""))
        ]
        return ", ".join(names[:2]) or None

    def _parse_job(self, board_token: str, job: dict[str, Any]) -> dict[str, Any] | None:
        title = _collapse_whitespace(str(job.get("title") or ""))
        url = _canonicalize_url(str(job.get("absolute_url") or ""))
        if not title or not url:
            return None

        content = _strip_html(str(job.get("content") or ""))
        location = self._job_location(job)
        department = self._job_department(job)
        description_parts = [
            content,
            f"Department: {department}." if department else "",
            f"Location: {location}." if location else "",
        ]
        description = _collapse_whitespace(" ".join(part for part in description_parts if part))
        company_name = board_token.replace("-", " ").replace("_", " ").title()
        updated_at = _parse_datetime(str(job.get("updated_at") or ""))

        return {
            "title": title[:220],
            "description": (description or f"Greenhouse job listing from {company_name}.")[:700],
            "url": url,
            "opportunity_type": _infer_opportunity_type(title, description or "job"),
            "university": company_name,
            "location": location,
            "deadline": updated_at + timedelta(days=45) if updated_at else None,
            "source": "greenhouse",
        }

    def fetch_live_opportunities(self, max_items: int = 40) -> list[dict]:
        opportunities: list[dict] = []
        errors: list[str] = []
        board_tokens = self._configured_board_tokens()
        per_board_limit = max(1, max_items // max(1, len(board_tokens)) + 1)

        for board_token in board_tokens:
            try:
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
                response = self.session.get(
                    api_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                jobs = payload.get("jobs") if isinstance(payload, dict) else None
                if not isinstance(jobs, list):
                    errors.append(f"{board_token}: unexpected Greenhouse response shape")
                    continue
                for job in jobs[:per_board_limit]:
                    if not isinstance(job, dict):
                        continue
                    parsed = self._parse_job(board_token, job)
                    if parsed:
                        opportunities.append(parsed)
                    if len(opportunities) >= max_items:
                        break
                if len(opportunities) >= max_items:
                    break
            except Exception as exc:
                errors.append(f"{board_token}: {exc}")

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
            if str(config.get("source") or "").strip() and config.get("enabled", True)
        }
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.source_card_profiles: dict[str, dict[str, Any]] = {
            "wellfound": {
                "card_selectors": ["div[data-testid='StartupResult']", "div[data-testid='JobListing']", "div.job-listing"],
                "title_selectors": ["a[data-testid='startup-name']", "a[data-testid='job-title']", "a[href*='/jobs/']"],
                "description_selectors": ["div[data-testid='job-description']", "div.details", "p"],
                "company_selectors": ["span[data-testid='startup-name']", "div[class*='company']", "a[data-testid='startup-name']"],
                "location_selectors": ["span[data-testid='job-location']", "div[class*='location']", "span"],
                "meta_selectors": ["div[class*='job-details']", "div.details", "ul"],
            },
            "instahyre": {
                "card_selectors": ["div.job-card", "div[data-cy='job-card']", "section[class*='job']"],
                "title_selectors": ["a[href*='/job/']", "h2", "h3"],
                "description_selectors": ["div.job-description", "div[class*='description']", "p"],
                "company_selectors": ["div.company-name", "span.company-name", "a[href*='/company/']"],
                "location_selectors": ["div.location", "span.location", "div[class*='location']"],
                "meta_selectors": ["div.job-info", "div[class*='metadata']", "ul"],
            },
            "hirist": {
                "card_selectors": ["div.job-card", "div[data-testid='job-card']", "div[class*='jobCard']"],
                "title_selectors": ["a[href*='job']", "h2", "h3"],
                "description_selectors": ["div.job-desc", "div[class*='desc']", "p"],
                "company_selectors": ["div.company", "span.company", "a[href*='/company/']"],
                "location_selectors": ["div.location", "span.location", "div[class*='location']"],
                "meta_selectors": ["div.job-meta", "div[class*='meta']", "ul"],
            },
            "cuvette": {
                "card_selectors": ["div[data-testid='job-card']", "div.job-card", "article"],
                "title_selectors": ["a[href*='/jobs/']", "h2", "h3"],
                "description_selectors": ["div[class*='description']", "p"],
                "company_selectors": ["div[class*='company']", "span[class*='company']", "h4"],
                "location_selectors": ["div[class*='location']", "span[class*='location']", "p"],
                "meta_selectors": ["div[class*='meta']", "div[class*='details']", "ul"],
            },
            "ycombinator_jobs": {
                "card_selectors": ["div.yc-job-card", "div[class*='job-card']", "article"],
                "title_selectors": ["a[href*='/jobs/']", "h2", "h3"],
                "description_selectors": ["div[class*='description']", "p"],
                "company_selectors": ["span[class*='company']", "div[class*='company']", "h4"],
                "location_selectors": ["span[class*='location']", "div[class*='location']", "p"],
                "meta_selectors": ["div[class*='meta']", "span[class*='salary']", "ul", "p"],
            },
            "promilo": {
                "card_selectors": ["div.promilo-job-card", "div[class*='job-card']", "article"],
                "title_selectors": ["a[href*='/jobs/']", "h2", "h3"],
                "description_selectors": ["div[class*='description']", "p"],
                "company_selectors": ["span[class*='company']", "div[class*='company']", "h4"],
                "location_selectors": ["span[class*='location']", "div[class*='location']", "p"],
                "meta_selectors": ["div[class*='details']", "div[class*='meta']", "ul", "p"],
            },
            "major_league_hacking": {
                "card_selectors": ["div.event", "article", "li"],
                "title_selectors": ["a[href*='mlh.io']", "h2", "h3"],
                "description_selectors": ["p", "div[class*='details']"],
                "company_selectors": ["span[class*='host']", "div[class*='host']", "span[class*='organizer']"],
                "location_selectors": ["span[class*='location']", "div[class*='location']", "p"],
                "meta_selectors": ["div[class*='details']", "ul", "p"],
            },
            "linkedin": {
                "card_selectors": ["div.base-card", "li", "div.job-search-card"],
                "title_selectors": ["a.base-card__full-link", "a[href*='/jobs/view/']", "h3"],
                "description_selectors": ["h4", "span.job-search-card__snippet", "p"],
                "company_selectors": ["h4.base-search-card__subtitle", "a.hidden-nested-link", "span.base-search-card__subtitle"],
                "location_selectors": ["span.job-search-card__location", "span.base-search-card__metadata"],
                "meta_selectors": ["div.base-card__metadata", "span.base-search-card__metadata", "ul"],
            },
            "devfolio": {
                "card_selectors": ["a[href*='/hackathons/']", "div[class*='HackathonCard']", "article"],
                "title_selectors": ["h3", "h2", "a[href*='/hackathons/']"],
                "description_selectors": ["p", "div[class*='description']", "div[class*='details']"],
                "company_selectors": ["span[class*='host']", "div[class*='host']", "span"],
                "meta_selectors": ["div[class*='details']", "ul", "p"],
            },
            "devpost": {
                "card_selectors": ["div.challenge-listing", "div.hackathon-tile", "article"],
                "title_selectors": ["a[href*='/software/']", "h3", "h2"],
                "description_selectors": ["p", "div[class*='description']", "div[class*='caption']"],
                "company_selectors": ["span[class*='organization']", "div[class*='organization']", "span"],
                "meta_selectors": ["div[class*='meta']", "ul", "p"],
            },
            "hackerearth": {
                "card_selectors": ["div.challenge-card-modern", "div.challenge-card", "article"],
                "title_selectors": ["a[href*='/challenges/']", "h3", "h2"],
                "description_selectors": ["p", "div[class*='description']", "div[class*='challenge-content']"],
                "company_selectors": ["div[class*='company']", "span[class*='company']", "span"],
                "meta_selectors": ["div[class*='meta']", "ul", "p"],
            },
            "reskilll": {
                "card_selectors": ["div[class*='hackathon']", "article", "a[href*='/event/']"],
                "title_selectors": ["h3", "h2", "a[href*='/event/']"],
                "description_selectors": ["p", "div[class*='description']", "div[class*='details']"],
                "company_selectors": ["span[class*='host']", "div[class*='host']", "span"],
                "meta_selectors": ["div[class*='details']", "ul", "p"],
            },
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

    def _extract_from_json_payload(
        self,
        payload: Any,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        opportunities: list[dict] = []
        if source_name == "remotive" and isinstance(payload, dict):
            rows = payload.get("jobs") or []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                description = _strip_html(str(row.get("description") or ""))
                opportunities.append(
                    {
                        "title": row.get("title"),
                        "description": description,
                        "url": row.get("url"),
                        "opportunity_type": default_type,
                        "university": row.get("company_name") or default_university,
                        "location": row.get("candidate_required_location"),
                        "stipend": row.get("salary"),
                        "created_at": _parse_datetime(row.get("publication_date")),
                        "tags": list(row.get("tags") or []),
                        "source": source_name,
                    }
                )
        elif source_name in {"remoteok", "remoteok_asia", "remoteok_europe"} and isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict) or not row.get("position"):
                    continue
                description = _strip_html(str(row.get("description") or ""))
                location = _collapse_whitespace(str(row.get("location") or "Remote"))
                region_text = f"{location} {description}".lower()
                if source_name == "remoteok_asia" and not re.search(
                    r"\basia\b|\bindia\b|\bsingapore\b|\bjapan\b|\bkorea\b|\bindonesia\b|\bphilippines\b",
                    region_text,
                ):
                    continue
                if source_name == "remoteok_europe" and not re.search(
                    r"\beurope\b|\beu\b|\buk\b|\bgermany\b|\bfrance\b|\bspain\b|\bitaly\b|\bnetherlands\b",
                    region_text,
                ):
                    continue
                opportunities.append(
                    {
                        "title": row.get("position"),
                        "description": description,
                        "url": row.get("url") or (
                            f"https://remoteok.com/remote-jobs/{row.get('id')}" if row.get("id") else None
                        ),
                        "opportunity_type": default_type,
                        "university": row.get("company") or default_university,
                        "location": location,
                        "created_at": _parse_datetime(row.get("date")),
                        "tags": list(row.get("tags") or []),
                        "source": source_name,
                    }
                )
        return [row for row in opportunities if row.get("title") and row.get("url")]

    def _extract_from_rss(
        self,
        xml_text: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        opportunities: list[dict] = []
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return opportunities
        for item in channel.findall("item"):
            title = _collapse_whitespace(item.findtext("title"))
            url = _collapse_whitespace(item.findtext("link"))
            description = _strip_html(item.findtext("description") or "")
            if not title or not url:
                continue
            company, separator, role = title.partition(":")
            opportunities.append(
                {
                    "title": role.strip() if separator else title,
                    "description": description,
                    "url": url,
                    "opportunity_type": default_type,
                    "university": company.strip() if separator else default_university,
                    "created_at": _parse_datetime(item.findtext("pubDate")),
                    "source": source_name,
                }
            )
        return opportunities

    def _github_readme_candidates(self, listing_url: str) -> list[str]:
        parsed = urlparse(listing_url)
        host = (parsed.hostname or "").lower()
        if host == "raw.githubusercontent.com":
            return [listing_url]
        if host != "github.com":
            return [listing_url]

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2:
            return [listing_url]
        owner, repo = path_parts[0], path_parts[1]
        branches = ["dev", "master", "main"]
        return [f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md" for branch in branches]

    def _github_source_permalink(self, listing_url: str, title: str, row_number: int) -> str:
        parsed = urlparse(listing_url)
        if (parsed.hostname or "").lower() != "github.com":
            return listing_url
        anchor = re.sub(r"[^a-z0-9 -]", "", _collapse_whitespace(title).lower())
        anchor = re.sub(r"\s+", "-", anchor).strip("-")
        row_key = anchor or f"row-{row_number}"
        separator = "&" if parsed.query else "?"
        return f"{listing_url.rstrip('/')}{separator}opportunity={row_key}"

    def _clean_markdown_cell(self, value: str) -> str:
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value or "")
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return _collapse_whitespace(text).strip(" -*_`")

    def _extract_github_markdown_links(self, value: str) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", value or ""):
            label = self._clean_markdown_cell(match.group(1))
            url = _collapse_whitespace(match.group(2)).strip()
            if url.startswith(("http://", "https://")):
                links.append((label, url))
        return links

    def _extract_github_html_links(self, node: Any) -> list[tuple[str, str]]:
        links: list[tuple[str, str]] = []
        for anchor in node.select("a[href]"):
            href = _collapse_whitespace(anchor.get("href")).strip()
            if not href.startswith(("http://", "https://")):
                continue
            label = _collapse_whitespace(anchor.get_text(" ", strip=True))
            if not label:
                image = anchor.find("img")
                label = _collapse_whitespace(image.get("alt") if image else "")
            links.append((label, href))
        return links

    def _select_github_application_url(self, links: list[tuple[str, str]]) -> str:
        for label, candidate in links:
            label_text = label.lower()
            host = (urlparse(candidate).hostname or "").lower()
            if "simplify.jobs" in host and "apply" not in label_text:
                continue
            if "github.com" in host and not any(
                token in label_text for token in ("apply", "application", "job", "career", "posting")
            ):
                continue
            return candidate
        return ""

    def _github_listing_row(
        self,
        *,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
        row_number: int,
        company: str,
        title: str,
        location: str | None,
        application_url: str,
    ) -> dict | None:
        company = _collapse_whitespace(company)
        title = _collapse_whitespace(title)
        location = _collapse_whitespace(location)
        if not title or title.lower() in {"role", "position", "title"}:
            return None
        if any(re.search(pattern, title, re.IGNORECASE) for pattern in EXPERIENCED_ROLE_PATTERNS):
            return None

        opportunity_type = default_type
        if re.search(r"\bnew\s*grad|entry[-\s]?level|graduate\b", title, re.IGNORECASE):
            opportunity_type = "Job"
        elif re.search(r"\bintern|co[-\s]?op|apprentice\b", title, re.IGNORECASE):
            opportunity_type = "Internship"
        elif not re.search(r"\bintern|student|fellow|research|extern|new\s*grad|entry[-\s]?level|graduate\b", title, re.IGNORECASE):
            return None

        description_parts = [
            f"Curated GitHub opportunity list entry from {default_university}.",
            f"Company: {company or default_university}.",
        ]
        if location:
            description_parts.append(f"Location: {location}.")
        if application_url:
            description_parts.append(f"Application link observed in source row: {application_url}.")
        description = " ".join(description_parts)

        row = {
            "title": title[:220],
            "description": description[:700],
            "url": self._github_source_permalink(listing_url, f"{company} {title}", row_number),
            "opportunity_type": opportunity_type,
            "university": company or default_university,
            "location": location or None,
            "source": source_name,
            "source_id": _hash_key(f"{listing_url}:{row_number}:{company}:{title}:{application_url}")[:24],
            "tags": ["github-curated"],
        }
        if application_url:
            row["external_apply_url"] = application_url
        return row

    def _parse_github_html_tables(
        self,
        markdown: str,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        soup = BeautifulSoup(markdown, "html.parser")
        opportunities: list[dict] = []
        current_company = ""
        for row_number, row_node in enumerate(soup.select("tr"), start=1):
            cells = row_node.select("td")
            if len(cells) < 4:
                continue
            company = _collapse_whitespace(cells[0].get_text(" ", strip=True))
            if company == "↳" and current_company:
                company = current_company
            elif company and company != "↳":
                current_company = company
            title = _collapse_whitespace(cells[1].get_text(" ", strip=True))
            location = _collapse_whitespace(cells[2].get_text(" ", strip=True))
            links = self._extract_github_html_links(cells[3])
            application_url = self._select_github_application_url(links)
            parsed = self._github_listing_row(
                listing_url=listing_url,
                source_name=source_name,
                default_type=default_type,
                default_university=default_university,
                row_number=row_number,
                company=company,
                title=title,
                location=location,
                application_url=application_url,
            )
            if parsed:
                opportunities.append(parsed)
        return opportunities

    def _parse_github_markdown_listing(
        self,
        markdown: str,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        html_rows = self._parse_github_html_tables(
            markdown=markdown,
            listing_url=listing_url,
            source_name=source_name,
            default_type=default_type,
            default_university=default_university,
        )
        if html_rows:
            return html_rows

        opportunities: list[dict] = []
        for row_number, raw_line in enumerate(markdown.splitlines(), start=1):
            line = raw_line.strip()
            if not line.startswith("|") or line.count("|") < 3:
                continue
            lowered = line.lower()
            if re.search(r"\|\s*:?-{3,}:?\s*\|", lowered):
                continue
            if "company" in lowered and re.search(r"\b(role|position|title|location|application)\b", lowered):
                continue

            raw_cells = [cell.strip() for cell in line.strip("|").split("|")]
            cells = [self._clean_markdown_cell(cell) for cell in raw_cells]
            cells = [cell for cell in cells if cell and cell.lower() not in {"↳", "apply", "application"}]
            if len(cells) < 2:
                continue

            company = cells[0]
            title = cells[1] if len(cells) > 1 else cells[0]
            location = cells[2] if len(cells) > 2 else None

            application_links: list[tuple[str, str]] = []
            for raw_cell in raw_cells:
                application_links.extend(self._extract_github_markdown_links(raw_cell))
            row = self._github_listing_row(
                listing_url=listing_url,
                source_name=source_name,
                default_type=default_type,
                default_university=default_university,
                row_number=row_number,
                company=company,
                title=title,
                location=location,
                application_url=self._select_github_application_url(list(reversed(application_links))),
            )
            if row:
                opportunities.append(row)

        return opportunities

    def _extract_extern_cards(self, soup: BeautifulSoup, listing_url: str) -> list[dict]:
        opportunities: list[dict] = []
        seen_urls: set[str] = set()
        for card in soup.select(".externships_list .w-dyn-item, .externships-list_collection .w-dyn-item"):
            title = _collapse_whitespace(
                card.select_one(".externships_item-title").get_text(" ", strip=True)
                if card.select_one(".externships_item-title")
                else ""
            )
            link = card.select_one("a[href^='/externships/']")
            href = (link.get("href") or "").strip() if link else ""
            url = _canonicalize_url(urljoin(listing_url, href)) if href else ""
            if not title or not url or url in seen_urls:
                continue

            company = _collapse_whitespace(
                card.select_one(".externships_company-name-filter").get_text(" ", strip=True)
                if card.select_one(".externships_company-name-filter")
                else "Extern"
            )
            description = _collapse_whitespace(
                card.select_one(".externships_short-description").get_text(" ", strip=True)
                if card.select_one(".externships_short-description")
                else ""
            )
            tags = [
                _collapse_whitespace(node.get_text(" ", strip=True))
                for node in card.select(".title_tag, .externship_title-tag")
                if _collapse_whitespace(node.get_text(" ", strip=True))
            ]
            meta_text = " ".join(tags)
            start_match = re.search(r"Live Session Starts:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", meta_text)
            posted_match = re.search(r"published:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", meta_text, re.IGNORECASE)
            duration_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:weeks?|wks?)\b", meta_text, re.IGNORECASE)
            duration_months = None
            if duration_match:
                duration_months = round(float(duration_match.group(1)) / 4.345, 2)
            combined_description = " ".join(part for part in [description, meta_text] if part).strip()
            seen_urls.add(url)
            opportunities.append(
                {
                    "title": title[:220],
                    "description": (combined_description or f"Externship indexed from Extern.")[:700],
                    "url": url,
                    "opportunity_type": "Internship",
                    "university": company or "Extern",
                    "deadline": _parse_datetime(start_match.group(1)) if start_match else None,
                    "created_at": _parse_datetime(posted_match.group(1)) if posted_match else None,
                    "duration_months": duration_months,
                    "tags": [tag for tag in tags if len(tag) <= 80][:12],
                    "source": "extern",
                }
            )
        return opportunities

    def _fetch_github_markdown_opportunities(
        self,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        last_error: Exception | None = None
        for raw_url in self._github_readme_candidates(listing_url):
            try:
                response = self.session.get(
                    raw_url,
                    headers={**self.headers, "Accept": "text/plain,text/markdown,*/*"},
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                text = str(getattr(response, "text", "") or "")
                parsed = self._parse_github_markdown_listing(
                    markdown=text,
                    listing_url=listing_url,
                    source_name=source_name,
                    default_type=default_type,
                    default_university=default_university,
                )
                if parsed:
                    return parsed
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return []

    def _looks_like_candidate(self, title: str, url: str) -> bool:
        if not title or not url:
            return False
        normalized_title = title.strip().lower()
        if normalized_title in GENERIC_NON_OPPORTUNITY_ANCHORS:
            return False
        if re.fullmatch(
            r"(?:remote|blockchain|cryptocurrency)?\s*jobs?(?:\s+(?:anywhere|north america|latin america|europe|asia|middle east|africa|apac))?",
            normalized_title,
        ):
            return False
        if re.fullmatch(r"(?:remote\s+)?[a-z0-9 /&+-]+\s+jobs?", normalized_title):
            return False
        if any(
            phrase in normalized_title
            for phrase in (
                "post a job",
                "job alert",
                "resume review",
                "browse all jobs",
                "career center",
                "job application tracking",
                "hidden remote jobs",
            )
        ):
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

    def _extract_from_source_cards(
        self,
        soup: BeautifulSoup,
        listing_url: str,
        source_name: str,
        default_type: str,
        default_university: str,
    ) -> list[dict]:
        profile = self.source_card_profiles.get(source_name)
        if not profile:
            return []

        opportunities: list[dict] = []
        seen_urls: set[str] = set()
        card_selectors = profile.get("card_selectors") or []
        title_selectors = profile.get("title_selectors") or []
        description_selectors = profile.get("description_selectors") or []
        company_selectors = profile.get("company_selectors") or []
        location_selectors = profile.get("location_selectors") or []
        meta_selectors = profile.get("meta_selectors") or []

        cards: list[Any] = []
        for selector in card_selectors:
            cards.extend(soup.select(selector))
        for card in cards:
            title_node = None
            for selector in title_selectors:
                title_node = card.select_one(selector)
                if title_node is not None:
                    break
            if title_node is None:
                continue
            title = _collapse_whitespace(title_node.get_text(" ", strip=True))
            href = ""
            if title_node.name == "a":
                href = (title_node.get("href") or "").strip()
            elif title_node.find("a", href=True):
                href = (title_node.find("a", href=True).get("href") or "").strip()
            url = href if href.startswith("http") else urljoin(listing_url, href)
            url = _canonicalize_url(url)
            if not title or not url or url in seen_urls:
                continue

            description = ""
            for selector in description_selectors:
                node = card.select_one(selector)
                if node is not None:
                    description = _collapse_whitespace(node.get_text(" ", strip=True))
                    if description:
                        break
            if not description:
                description = _collapse_whitespace(card.get_text(" ", strip=True))
            if title and description.startswith(title):
                description = description[len(title):].strip(" -:|")
            company = ""
            for selector in company_selectors:
                node = card.select_one(selector)
                if node is not None:
                    company = _collapse_whitespace(node.get_text(" ", strip=True))
                    if company and company.lower() != title.lower():
                        break
            location = ""
            for selector in location_selectors:
                node = card.select_one(selector)
                if node is not None:
                    location = _collapse_whitespace(node.get_text(" ", strip=True))
                    if location:
                        break
            meta_text = ""
            for selector in meta_selectors:
                node = card.select_one(selector)
                if node is not None:
                    meta_text = _collapse_whitespace(node.get_text(" ", strip=True))
                    if meta_text:
                        break
            combined_description = " ".join(part for part in [description, meta_text, location] if part).strip()
            if not self._looks_like_candidate(title, url):
                continue
            seen_urls.add(url)
            opportunities.append(
                {
                    "title": title[:220],
                    "description": (combined_description or description or f"Opportunity indexed from {source_name.replace('_', ' ').title()}.")[:700],
                    "url": url,
                    "opportunity_type": default_type or _infer_opportunity_type(title, combined_description or description),
                    "university": company or default_university,
                    "location": location or None,
                    "deadline": _extract_deadline_from_text(combined_description or description),
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
                if normalized_source == "github_internship_lists":
                    opportunities.extend(
                        self._fetch_github_markdown_opportunities(
                            listing_url=listing_url,
                            source_name=normalized_source,
                            default_type=default_type,
                            default_university=default_university,
                        )
                    )
                    if len(opportunities) >= max_items:
                        break
                    continue

                response = self.session.get(
                    listing_url,
                    headers=self.headers,
                    timeout=settings.SCRAPER_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                content_type = str(response.headers.get("content-type") or "").lower()
                if "json" in content_type or listing_url.rstrip("/").endswith("/api"):
                    parsed = self._extract_from_json_payload(
                        payload=response.json(),
                        source_name=normalized_source,
                        default_type=default_type,
                        default_university=default_university,
                    )
                    opportunities.extend(parsed)
                    if len(opportunities) >= max_items:
                        break
                    continue
                if "rss" in content_type or "xml" in content_type or listing_url.endswith(".rss"):
                    parsed = self._extract_from_rss(
                        xml_text=response.text,
                        source_name=normalized_source,
                        default_type=default_type,
                        default_university=default_university,
                    )
                    opportunities.extend(parsed)
                    if len(opportunities) >= max_items:
                        break
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                if normalized_source == "extern":
                    parsed = self._extract_extern_cards(soup=soup, listing_url=listing_url)
                else:
                    parsed = self._extract_from_source_cards(
                        soup=soup,
                        listing_url=listing_url,
                        source_name=normalized_source,
                        default_type=default_type,
                        default_university=default_university,
                    )
                parsed.extend(
                    self._extract_from_ld_json(
                        soup=soup,
                        listing_url=listing_url,
                        source_name=normalized_source,
                        default_type=default_type,
                        default_university=default_university,
                    )
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

        opportunities = [
            row for row in _dedupe_by_url(opportunities)
            if is_early_career_opportunity(row)
        ][:max_items]
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
greenhouse_scraper = GreenhouseScraper()
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
        "parsed": 0,
        "inserted": 0,
        "updated": 0,
        "failed": 0,
        "deduplicated": 0,
        "avg_trust_score": None,
        "errors": [],
        "fetch_duration_ms": 0,
        "upsert_duration_ms": 0,
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
    now = _to_naive_utc(utc_now())
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
    opportunity_rows = list(opportunities)
    inserted_count = 0
    updated_count = 0
    failed_count = 0
    trust_scores: list[float] = []
    semantic_threshold = max(0.0, min(1.0, float(settings.SEMANTIC_DEDUP_THRESHOLD)))

    normalized_records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    out_of_scope_count = 0

    from app.services.opportunity_quality_service import opportunity_quality_scorer

    for opp_data in opportunity_rows:
        if not is_early_career_opportunity(opp_data):
            out_of_scope_count += 1
            continue
        url = (opp_data.get("url") or "").strip()
        if not is_valid_apply_url(url) or url in seen_urls:
            continue
        seen_urls.add(url)
        classification = ai_system.classify_opportunity(
            f"{opp_data.get('title', '')} {opp_data.get('description', '')}"
        )
        normalized_payload = _enrich_metadata(dict(opp_data))
        normalized_payload["url"] = normalized_payload.get("url") or url
        normalized_payload["deadline"] = _to_naive_utc(opp_data.get("deadline"))
        normalized_payload["domain"] = opp_data.get("domain") or classification["primary_domain"]
        normalized_payload["source"] = opp_data.get("source") or source_name.lower().replace(" ", "_")
        assessment = assess_opportunity_trust(normalized_payload)
        normalized_payload.update(assessment.as_update())
        trust_scores.append(float(assessment.trust_score))
        synthetic = type("OpportunityPayload", (), normalized_payload)()
        quality_updates = opportunity_quality_scorer.normalize_payload(synthetic)
        normalized_payload.update({key: value for key, value in quality_updates.items() if value is not None})
        quality_score, quality_missing_fields = opportunity_quality_scorer.score_payload(synthetic, quality_updates)
        normalized_payload["quality_score"] = quality_score
        normalized_payload["quality_missing_fields"] = quality_missing_fields
        normalized_payload["last_quality_run_at"] = _to_naive_utc(utc_now())
        normalized_records.append(normalized_payload)

    parsed_count = len(normalized_records)

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
    existing_by_key: dict[str, Any] = {}
    existing_by_cluster: dict[str, Any] = {}
    if normalized_records:
        existing_records = await Opportunity.find_many(
            In(Opportunity.url, [record["url"] for record in normalized_records])
        ).to_list()
        existing_by_url = {record.url: record for record in existing_records}
        canonical_keys = [str(record.get("canonical_key") or "").strip() for record in normalized_records]
        canonical_keys = [item for item in canonical_keys if item]
        if canonical_keys:
            key_records = await Opportunity.find_many(In(Opportunity.canonical_key, canonical_keys)).to_list()
            existing_by_key = {
                str(record.canonical_key or "").strip(): record
                for record in key_records
                if str(record.canonical_key or "").strip()
            }
        duplicate_cluster_keys = [str(record.get("duplicate_cluster_key") or "").strip() for record in normalized_records]
        duplicate_cluster_keys = [item for item in duplicate_cluster_keys if item]
        if duplicate_cluster_keys:
            cluster_records = await Opportunity.find_many(
                In(Opportunity.duplicate_cluster_key, duplicate_cluster_keys)
            ).to_list()
            existing_by_cluster = {
                str(record.duplicate_cluster_key or "").strip(): record
                for record in cluster_records
                if str(record.duplicate_cluster_key or "").strip()
            }

    from app.services.vector_service import opportunity_vector_service

    if normalized_records:
        await opportunity_vector_service.rebuild()

    for normalized_payload in normalized_records:
        url = normalized_payload["url"]

        try:
            now_naive = _to_naive_utc(utc_now())
            canonical_key = str(normalized_payload.get("canonical_key") or "").strip()
            duplicate_cluster_key = str(normalized_payload.get("duplicate_cluster_key") or "").strip()
            existing = (
                existing_by_url.get(url)
                or existing_by_key.get(canonical_key)
                or existing_by_cluster.get(duplicate_cluster_key)
            )
            if existing:
                changed = False
                for field in [
                    "title",
                    "description",
                    "opportunity_type",
                    "university",
                    "deadline",
                    "source",
                    "source_id",
                    "domain",
                    "location",
                    "work_mode",
                    "stipend",
                    "stipend_min",
                    "stipend_max",
                    "stipend_currency",
                    "stipend_period",
                    "eligibility",
                    "batch_years",
                    "ppo_available",
                    "tags",
                    "quality_score",
                    "quality_missing_fields",
                    "last_quality_run_at",
                    "canonical_key",
                    "canonical_url_hash",
                    "title_company_location_hash",
                    "duplicate_cluster_key",
                    "normalized_title",
                    "normalized_organization",
                    "duration_months",
                ]:
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
                existing_by_url[existing.url] = existing
                if canonical_key:
                    existing_by_key[canonical_key] = existing
                if duplicate_cluster_key:
                    existing_by_cluster[duplicate_cluster_key] = existing
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
                duplicate = await Opportunity.find_one({"url": duplicate_url})
                if duplicate:
                    changed = False
                    for field in [
                        "canonical_key",
                        "canonical_url_hash",
                        "title_company_location_hash",
                        "duplicate_cluster_key",
                        "normalized_title",
                        "normalized_organization",
                        "location",
                        "work_mode",
                        "stipend",
                        "stipend_min",
                        "stipend_max",
                        "stipend_currency",
                        "stipend_period",
                        "eligibility",
                        "batch_years",
                        "ppo_available",
                        "tags",
                        "quality_score",
                        "quality_missing_fields",
                        "last_quality_run_at",
                        "duration_months",
                    ]:
                        incoming = normalized_payload.get(field)
                        if incoming is None:
                            continue
                        if getattr(duplicate, field, None) != incoming:
                            setattr(duplicate, field, incoming)
                            changed = True
                    duplicate.last_seen_at = now_naive
                    if changed:
                        duplicate.updated_at = now_naive
                    await duplicate.save()
                    duplicate_key = str(getattr(duplicate, "canonical_key", "") or "").strip()
                    duplicate_cluster = str(getattr(duplicate, "duplicate_cluster_key", "") or "").strip()
                    existing_by_url[duplicate.url] = duplicate
                    if duplicate_key:
                        existing_by_key[duplicate_key] = duplicate
                    if duplicate_cluster:
                        existing_by_cluster[duplicate_cluster] = duplicate
                    updated_count += 1
                    continue

            opportunity = Opportunity(
                **normalized_payload,
                updated_at=now_naive,
                last_seen_at=now_naive,
            )
            await opportunity.insert()
            inserted_count += 1
            existing_by_url[opportunity.url] = opportunity
            opportunity_key = str(getattr(opportunity, "canonical_key", "") or "").strip()
            opportunity_cluster = str(getattr(opportunity, "duplicate_cluster_key", "") or "").strip()
            if opportunity_key:
                existing_by_key[opportunity_key] = opportunity
            if opportunity_cluster:
                existing_by_cluster[opportunity_cluster] = opportunity

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

    return {
        "inserted": inserted_count,
        "updated": updated_count,
        "failed": failed_count,
        "parsed": parsed_count,
        "out_of_scope": out_of_scope_count,
        "deduplicated": max(0, len(opportunity_rows) - out_of_scope_count - len(normalized_records)),
        "avg_trust_score": round(sum(trust_scores) / len(trust_scores), 2) if trust_scores else None,
    }


async def run_scheduled_scrapers(force: bool = False) -> dict[str, Any]:
    """
    Resilient background job for live opportunity data ingestion:
    1) Ivy League feeds
    2) Unstop opportunities
    3) Core Indian opportunity boards (Naukri, Internshala, Hack2Skill,
       Freshersworld, Indeed India, and Greenhouse company boards)
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
            system_user = await User.find_one({"is_admin": True})
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
                asyncio.to_thread(
                    greenhouse_scraper.fetch_live_opportunities,
                    max(1, settings.SCRAPER_GREENHOUSE_MAX_ITEMS),
                ),
                return_exceptions=True,
            )
            portal_specs: list[tuple[str, str]] = [
                (
                    str(config.get("source") or "").strip().lower(),
                    str(config.get("label") or config.get("source") or "Platform").strip(),
                )
                for config in GENERIC_PORTAL_LISTINGS
                if str(config.get("source") or "").strip() and config.get("enabled", True)
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
                greenhouse_result,
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
                fetch_started_at = time.perf_counter()
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

                    source_report["fetch_duration_ms"] = round((time.perf_counter() - fetch_started_at) * 1000, 1)
                    upsert_started_at = time.perf_counter()
                    insert_stats = await _insert_and_broadcast(
                        opportunities=opportunities,
                        source_name=source_label,
                        system_user_id=system_user_id,
                        ai_system=ai_system,
                        Opportunity=Opportunity,
                        Post=Post,
                    )
                    source_report.update(insert_stats)
                    source_report["upsert_duration_ms"] = round((time.perf_counter() - upsert_started_at) * 1000, 1)
                except Exception as exc:
                    source_report["fetch_duration_ms"] = round((time.perf_counter() - fetch_started_at) * 1000, 1)
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
            await _process_source_result(
                source_key="greenhouse",
                source_label="Greenhouse",
                result=greenhouse_result,
                empty_message="No opportunities parsed from Greenhouse.",
            )

            for (source_name, source_label), source_result in zip(portal_specs, portal_fetch_results):
                await _process_source_result(
                    source_key=source_name,
                    source_label=source_label,
                    result=source_result,
                    empty_message=f"No opportunities parsed from {source_label}.",
                )

            try:
                from app.services.source_discovery import TemplateDrivenScraper, scraper_registry

                dynamic_registrations = await scraper_registry.all_active()
                dynamic_scraper = TemplateDrivenScraper()
                for registration in dynamic_registrations[:50]:
                    source_report = _new_source_report(registration.scraper_key)
                    fetch_started_at = time.perf_counter()
                    try:
                        scrape_result = await dynamic_scraper.scrape(registration)
                        source_report["fetched"] = len(scrape_result.items)
                        source_report["parsed"] = int(scrape_result.items_parsed)
                        source_report["errors"].extend(scrape_result.errors)
                        dynamic_opportunities = [
                            {
                                "title": row.get("title"),
                                "description": row.get("description_preview")
                                or row.get("description")
                                or f"Opportunity indexed from {registration.source_name}.",
                                "url": row.get("apply_url") or row.get("url"),
                                "opportunity_type": str(row.get("opportunity_type") or "Opportunity").title(),
                                "university": row.get("company") or registration.source_name,
                                "source": registration.scraper_key,
                                "source_id": registration.discovered_source_id,
                                "domain": registration.domain,
                                "location": row.get("location"),
                                "work_mode": row.get("work_mode"),
                                "stipend": row.get("stipend_text") or row.get("stipend"),
                                "deadline": _parse_datetime(row.get("deadline_text") or row.get("deadline")),
                            }
                            for row in scrape_result.items
                            if row.get("title") and (row.get("apply_url") or row.get("url"))
                        ]
                        source_report["fetch_duration_ms"] = round((time.perf_counter() - fetch_started_at) * 1000, 1)
                        upsert_started_at = time.perf_counter()
                        insert_stats = await _insert_and_broadcast(
                            opportunities=dynamic_opportunities,
                            source_name=registration.source_name,
                            system_user_id=system_user_id,
                            ai_system=ai_system,
                            Opportunity=Opportunity,
                            Post=Post,
                        )
                        source_report.update(insert_stats)
                        source_report["upsert_duration_ms"] = round((time.perf_counter() - upsert_started_at) * 1000, 1)
                        registration.last_scraped_at = utc_now()
                        registration.total_yield += int(insert_stats.get("inserted", 0) or 0) + int(insert_stats.get("updated", 0) or 0)
                        if scrape_result.errors or scrape_result.parse_success_rate < 0.6:
                            registration.consecutive_failures += 1
                            registration.stale_template_failures += 1
                            registration.health_score = max(0.0, float(registration.health_score or 100.0) - 15.0)
                        else:
                            registration.consecutive_failures = 0
                            registration.stale_template_failures = 0
                            registration.health_score = min(100.0, float(registration.health_score or 100.0) + 5.0)
                        if registration.consecutive_failures >= 3:
                            registration.updated_at = utc_now()
                            await registration.save()
                            await scraper_registry.quarantine(registration.scraper_key, "dynamic_parse_failures")
                        else:
                            registration.updated_at = utc_now()
                            await registration.save()
                    except Exception as exc:
                        source_report["fetch_duration_ms"] = round((time.perf_counter() - fetch_started_at) * 1000, 1)
                        source_report["errors"].append(str(exc))
                        registration.consecutive_failures += 1
                        registration.health_score = max(0.0, float(registration.health_score or 100.0) - 20.0)
                        if registration.consecutive_failures >= 3:
                            registration.updated_at = utc_now()
                            await registration.save()
                            await scraper_registry.quarantine(registration.scraper_key, "dynamic_scrape_error")
                        else:
                            registration.updated_at = utc_now()
                            await registration.save()
                    report_sources.append(source_report)
            except Exception as exc:
                source_report = _new_source_report("dynamic_discovered_sources")
                source_report["errors"].append(f"dynamic_source_registry_error:{exc}")
                report_sources.append(source_report)

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

            try:
                from app.services.scraper_health_service import scraper_health_service

                await scraper_health_service.persist_report(report)
            except Exception as exc:
                logger.warning("Failed to persist scraper run logs: %s", exc)

            print(
                f"[ScraperEngine] Completed ({status}) | "
                f"fetched={totals['fetched']} inserted={totals['inserted']} "
                f"updated={totals['updated']} deleted={totals['deleted']}"
            )
            return report
        finally:
            _scraper_runtime_state["is_running"] = False
