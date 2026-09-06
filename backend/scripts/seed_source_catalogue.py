"""A broad, audience-tagged source catalogue, verified before it is written.

The corpus grew from a handful of scrapers aimed at one audience. This is the
catalogue that moves it past that: candidates across students, academicians and
institutions, each tagged with who it serves so the audience travels through
discovery into the opportunities it yields.

Nothing here is trusted on my say-so. Every entry is fetched and checked for
wording that indicates it advertises positions, and only entries that respond are
written. That check exists because the earlier AYUSH round verified reachability
instead - every seed passed, and 14 of 16 were then rejected downstream for
having no opportunities on the page. Reachability was a property nobody doubted.

Robots and rate limits are enforced downstream by the qualification pipeline,
which refuses sources that disallow crawling; this script proposes candidates, it
does not grant permission to scrape them.

Dry run by default.

    python scripts/seed_source_catalogue.py                      # probe all
    python scripts/seed_source_catalogue.py --audience faculty   # one audience
    python scripts/seed_source_catalogue.py --apply              # write passes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class Source:
    name: str
    domain: str
    url: str
    audience: str
    category: str


STUDENT_SOURCES: tuple[Source, ...] = tuple(
    Source(n, d, u, "student", c)
    for n, d, u, c in (
        ("Internshala", "internshala.com", "https://internshala.com/internships", "job_board"),
        ("Unstop", "unstop.com", "https://unstop.com/internships", "job_board"),
        ("Naukri Campus", "naukri.com", "https://www.naukri.com/internship-jobs", "job_board"),
        ("Foundit", "foundit.in", "https://www.foundit.in/search/internship-jobs", "job_board"),
        ("Shine", "shine.com", "https://www.shine.com/job-search/internship-jobs", "job_board"),
        ("TimesJobs", "timesjobs.com", "https://www.timesjobs.com/", "job_board"),
        ("Freshersworld", "freshersworld.com", "https://www.freshersworld.com/jobs/", "job_board"),
        ("Hirist", "hirist.tech", "https://www.hirist.tech/", "job_board"),
        ("Instahyre", "instahyre.com", "https://www.instahyre.com/", "job_board"),
        ("Cutshort", "cutshort.io", "https://cutshort.io/jobs", "job_board"),
        ("Apna", "apna.co", "https://apna.co/jobs", "job_board"),
        ("National Career Service", "ncs.gov.in", "https://www.ncs.gov.in/", "government"),
        ("Employment News", "employmentnews.gov.in", "https://employmentnews.gov.in/newemp/home.aspx", "government"),
        ("ISRO Careers", "isro.gov.in", "https://www.isro.gov.in/Careers.html", "government"),
        ("DRDO Careers", "drdo.gov.in", "https://www.drdo.gov.in/drdo/careers-drdo", "government"),
        ("Wellfound", "wellfound.com", "https://wellfound.com/jobs", "startup"),
        ("Y Combinator Jobs", "ycombinator.com", "https://www.ycombinator.com/jobs", "startup"),
        ("RemoteOK", "remoteok.com", "https://remoteok.com/", "remote"),
        ("We Work Remotely", "weworkremotely.com", "https://weworkremotely.com/", "remote"),
        ("Devfolio", "devfolio.co", "https://devfolio.co/hackathons", "hackathon"),
        ("Devpost", "devpost.com", "https://devpost.com/hackathons", "hackathon"),
        ("MLH", "mlh.io", "https://mlh.io/seasons/2026/events", "hackathon"),
        ("Buddy4Study", "buddy4study.com", "https://www.buddy4study.com/scholarships", "scholarship"),
        ("National Scholarship Portal", "scholarships.gov.in", "https://scholarships.gov.in/", "scholarship"),
    )
)

FACULTY_SOURCES: tuple[Source, ...] = tuple(
    Source(n, d, u, "faculty", c)
    for n, d, u, c in (
        ("NITTTR Kolkata", "nitttrkol.ac.in", "https://www.nitttrkol.ac.in/", "fdp"),
        ("NITTTR Chennai", "nitttrc.ac.in", "https://www.nitttrc.ac.in/", "fdp"),
        ("ICSSR", "icssr.org", "https://icssr.org/", "research_grant"),
        ("ICAR", "icar.org.in", "https://icar.org.in/", "research_grant"),
        ("ICMR", "icmr.gov.in", "https://www.icmr.gov.in/", "research_grant"),
        ("NPTEL", "nptel.ac.in", "https://nptel.ac.in/", "fdp"),
        ("INFLIBNET", "inflibnet.ac.in", "https://www.inflibnet.ac.in/", "academic_recruitment"),
        ("Vidwan Expert Database", "vidwan.inflibnet.ac.in", "https://vidwan.inflibnet.ac.in/", "academic_recruitment"),
        ("IISc Careers", "iisc.ac.in", "https://iisc.ac.in/careers/", "academic_recruitment"),
        ("IIT Delhi", "iitd.ac.in", "https://home.iitd.ac.in/", "academic_recruitment"),
        ("IIT Madras", "iitm.ac.in", "https://www.iitm.ac.in/", "academic_recruitment"),
        ("IIT Kanpur", "iitk.ac.in", "https://www.iitk.ac.in/", "academic_recruitment"),
        ("TIFR", "tifr.res.in", "https://www.tifr.res.in/", "academic_recruitment"),
        ("JNU", "jnu.ac.in", "https://www.jnu.ac.in/", "academic_recruitment"),
        ("University of Delhi", "du.ac.in", "https://www.du.ac.in/", "academic_recruitment"),
        ("DBT India", "dbtindia.gov.in", "https://dbtindia.gov.in/", "research_grant"),
        ("SPARC", "sparc.iitkgp.ac.in", "https://sparc.iitkgp.ac.in/", "collaboration"),
    )
)

INSTITUTION_SOURCES: tuple[Source, ...] = tuple(
    Source(n, d, u, "institution", c)
    for n, d, u, c in (
        ("NAAC", "naac.gov.in", "http://www.naac.gov.in/", "accreditation"),
        ("NIRF", "nirfindia.org", "https://www.nirfindia.org/", "ranking"),
        ("NBA India", "nbaind.org", "https://www.nbaind.org/", "accreditation"),
        ("MoE Innovation Cell", "mic.gov.in", "https://mic.gov.in/", "collaboration"),
        ("Institution Innovation Council", "iic.mic.gov.in", "https://iic.mic.gov.in/", "collaboration"),
        ("AICTE Schemes", "aicte-india.org", "https://www.aicte-india.org/schemes", "scheme"),
        ("UGC Schemes", "ugc.gov.in", "https://www.ugc.gov.in/", "scheme"),
        ("Startup India", "startupindia.gov.in", "https://www.startupindia.gov.in/", "collaboration"),
        ("Atal Innovation Mission", "aim.gov.in", "https://aim.gov.in/", "collaboration"),
    )
)

ALL_SOURCES = STUDENT_SOURCES + FACULTY_SOURCES + INSTITUTION_SOURCES

# Wording that indicates a page advertises something someone can apply to. Kept
# broad across audiences: an institution's page offers schemes and collaborations
# rather than vacancies, and would score zero against a jobs-only vocabulary.
_SIGNALS = (
    "vacanc", "recruit", "advertisement", "applications are invited", "apply",
    "internship", "job", "career", "opportunit", "fellowship", "scholarship",
    "hackathon", "faculty development", "fdp", "refresher", "grant", "scheme",
    "notification", "walk-in", "post of", "appointment", "collaborat", "programme",
)


async def probe(source: Source, *, timeout: float) -> tuple[bool, str, int]:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; VidyaVerse/1.0; +seed-check)"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers, verify=False
        ) as client:
            response = await client.get(source.url)
            if response.status_code >= 500:
                return False, f"HTTP {response.status_code}", 0
            body = (response.text or "").lower()
            signals = sum(1 for term in _SIGNALS if term in body)
            note = f"HTTP {response.status_code}, {signals} signal(s)" if signals else f"HTTP {response.status_code}, no wording"
            return True, note, signals
    except Exception as exc:  # noqa: BLE001 - the reason is the output
        return False, type(exc).__name__, 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--audience", choices=("student", "faculty", "institution"), default=None)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--min-signals",
        type=int,
        default=1,
        help="skip sources showing fewer than this many opportunity words (default 1)",
    )
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.models.source_discovery import CompanySeed

    await init_database()

    catalogue = [s for s in ALL_SOURCES if not args.audience or s.audience == args.audience]
    print(f"Probing {len(catalogue)} sources…\n")
    results = await asyncio.gather(*(probe(s, timeout=args.timeout) for s in catalogue))

    passed: list[Source] = []
    for source, (ok, note, signals) in zip(catalogue, results):
        usable = ok and signals >= args.min_signals
        mark = "ok  " if usable else ("thin" if ok else "FAIL")
        print(f"  [{mark}] {source.audience:<12} {source.name:<34} {note}")
        if usable:
            passed.append(source)

    print(f"\n{len(passed)}/{len(catalogue)} usable")

    created = skipped = 0
    for source in passed:
        if await CompanySeed.find_one(CompanySeed.domain == source.domain) is not None:
            skipped += 1
            continue
        created += 1
        if args.apply:
            await CompanySeed(
                company_name=source.name,
                domain=source.domain,
                careers_url=source.url,
                audience=source.audience,
                industry=source.category,
                company_size="large",
                source_category=f"{source.audience}_{source.category}",
                priority_tier=source.audience,
                notes=f"Catalogue seed for {source.audience} audience.",
                added_by="seed_source_catalogue",
                check_cadence_hours=72,
            ).insert()

    print(f"{'created' if args.apply else 'would create'}: {created}    already present: {skipped}")
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
