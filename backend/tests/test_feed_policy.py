from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.feed_policy import listing_rejection_reason, resolve_portal, resolved_type
from app.services.opportunity_visibility import is_student_visible_opportunity
from app.services.scraper import _resolve_listing_type, is_probable_opportunity_posting


CASES = [
    ("Internshala", "https://internshala.com/internships", "Internship", False),
    ("TensorHack Opportunities", "https://tensorhack.com/opportunities", "Internship", False),
    ("Campus Internships", "https://example.com/campus", "Internship", False),
    ("Entry Level 5434", "https://example.com/search", "Job", False),
    ("Browse remote jobs", "https://example.com/search", "Job", False),
    ("Upcoming Hackathons", "https://devpost.com/hackathons", "Hackathon", False),
    ("Software Engineer", "https://jobs.lever.co/acme", "Job", False),
    ("Backend Intern", "https://jobs.ashbyhq.com/acme?utm_source=test", "Internship", False),
    ("Graduate Analyst", "https://example.com/jobs?location=India", "Job", False),
    ("Graduate Analyst", "https://example.com/?utm_campaign=jobs", "Job", False),
    ("Student AI Hackathon", "https://devfolio.co", "Hackathon", False),
    ("Help for interns", "https://support.example.com/interns", "Internship", False),
    ("Immunefi Bug Bounties", "https://example.com/bounties", "Internship", False),
    ("NLnet Open Calls", "https://example.com/grants", "Opportunity", False),
    ("Senior Backend Engineer", "https://example.com/role/123", "Internship", False),
    ("Staff Data Scientist", "https://example.com/role/123", "Job", False),
    ("Student AI Hackathon", "javascript:alert(1)", "Hackathon", False),
    ("Software Engineering Intern", "https://job-boards.greenhouse.io/acme/jobs/123", "Internship", True),
    ("Software Engineer, New Grad", "https://jobs.lever.co/acme/abc-123", "Job", True),
    ("Research Engineer Intern", "https://jobs.ashbyhq.com/acme/abc-123", "Internship", True),
    ("Python Internship", "https://in.indeed.com/rc/clk?jk=abc123", "Internship", True),
    ("Graduate Analyst", "https://example.com/jobs?jobId=123", "Job", True),
    ("Backend Intern", "https://boards.greenhouse.io/acme?gh_jid=123", "Internship", True),
    ("Student AI Hackathon", "https://hackmit.org", "Hackathon", True),
    ("International Innovation Summit", "https://example.com/events/innovation", "Conference", True),
    ("AI for Developers Workshop", "https://example.com/events/ai", "Workshop", True),
    ("Python Internship", "https://example.com/role/123", "Internship", True),
    ("Security Engineer - Bug Bounty Team", "https://example.com/role/123", "Job", True),
]


def record_for(title, url, kind):
    return {"title": title, "url": url, "opportunity_type": kind, "source": "fixture", "description": "Develop projects alongside engineers and participate in workshops.", "portal_category": None, "url_liveness_status": "alive"}


@pytest.mark.parametrize("title,url,kind,visible", CASES)
def test_admission_contract(title, url, kind, visible):
    row = record_for(title, url, kind)
    reason = listing_rejection_reason(row, allowed_types=settings.OPPORTUNITY_SCOPE_TYPES)
    assert (reason is None) is visible, reason
    assert is_student_visible_opportunity(SimpleNamespace(**row)) is visible


@pytest.mark.parametrize("title,kind,portal,expected", [
    ("International Innovation Summit", "Conference", "career", "competitive"),
    ("Workshop for Engineers", "Workshop", None, "competitive"),
    ("Student AI Hackathon", "Internship", "career", "competitive"),
    ("Backend Engineer", "Job", "competitive", "career"),
    ("Research Engineer", "Research", None, "career"),
    ("Conference Coordinator", "Job", None, "career"),
    ("Hiring Challenge", "Hiring Challenge", "competitive", "career"),
    ("Immunefi Bug Bounties", "Internship", "career", "other"),
    ("World Innovation", "Opportunity", None, "other"),
])
def test_routing_ignores_incidental_description_and_stale_category(title, kind, portal, expected):
    assert resolve_portal(kind, title, portal) == expected


def test_ingestion_corrects_source_defaults():
    assert _resolve_listing_type("Student AI Hackathon", "Hiring engineers", "Internship") == "Hackathon"
    assert resolved_type("Job", "Research Intern") == "Internship"
    assert is_probable_opportunity_posting(record_for("Student AI Hackathon", "https://hackmit.org", "Hackathon"))


def test_source_name_and_dead_links_are_not_listings():
    row = record_for("Example Board", "https://example.com/role/123", "Internship")
    row["source"] = "example_board"
    assert listing_rejection_reason(row) == "portal_title"
    row["title"] = "Python Internship"
    row["url_liveness_status"] = "dead"
    assert listing_rejection_reason(row) == "dead_url"
