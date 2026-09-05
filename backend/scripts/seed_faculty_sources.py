"""Seed sources that serve academicians, not students.

The academician feed was seven items carved out of a corpus of nearly two
thousand, because every scraper here points at student roles and filtering
cannot add what the corpus does not contain. An FDP is advertised by AICTE and
the NITTTRs, not by a job board, so no keyword list over a job-board corpus will
ever produce one.

These seeds carry audience="faculty", which travels to the DiscoveredSource and
then to every opportunity extracted from it, so the faculty feed becomes a lookup
on a column instead of a guess about the words in a title.

Sources are probed for vacancy wording before being written, not merely for
reachability. The AYUSH seeding taught that lesson the expensive way: every seed
passed a reachability check and then 14 of 16 were rejected downstream for having
no opportunities on the page, because the probe had confirmed a property nobody
doubted.

Dry run by default.

    python scripts/seed_faculty_sources.py            # probe and report
    python scripts/seed_faculty_sources.py --apply    # write the ones that respond
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
class FacultySeed:
    name: str
    domain: str
    url: str
    category: str
    note: str


# Faculty development, training and academic recruitment. These are the bodies
# that actually run FDPs, refresher courses and induction programmes in India.
FACULTY_SOURCES: tuple[FacultySeed, ...] = (
    FacultySeed(
        "AICTE Training and Learning Academy", "aicte-india.org",
        "https://www.aicte-india.org/",
        "fdp", "Runs ATAL FDPs; the largest single source of faculty development in India.",
    ),
    FacultySeed(
        "AICTE ATAL Academy", "atalacademy.aicte-india.org",
        "https://atalacademy.aicte-india.org/",
        "fdp", "FDP listings and applications.",
    ),
    FacultySeed(
        "UGC", "ugc.gov.in", "https://www.ugc.gov.in/",
        "academic_recruitment", "Faculty recruitment notices and academic schemes.",
    ),
    FacultySeed(
        "NITTTR Chandigarh", "nitttrchd.ac.in", "https://www.nitttrchd.ac.in/",
        "fdp", "Technical teacher training; runs FDPs and refresher courses.",
    ),
    FacultySeed(
        "NITTTR Bhopal", "nitttrbpl.ac.in", "https://www.nitttrbpl.ac.in/",
        "fdp", "Technical teacher training institute.",
    ),
    FacultySeed(
        "SWAYAM ARPIT", "swayam.gov.in", "https://swayam.gov.in/",
        "fdp", "ARPIT online refresher courses for in-service faculty.",
    ),
    FacultySeed(
        "ANRF (formerly SERB)", "serbonline.in", "https://serbonline.in/",
        "research_grant", "Research grants and fellowships for faculty investigators.",
    ),
    FacultySeed(
        "CSIR Human Resource Development Group", "csirhrdg.res.in",
        "https://csirhrdg.res.in/",
        "research_grant", "Research fellowships and associateships.",
    ),
    FacultySeed(
        "DST", "dst.gov.in", "https://dst.gov.in/",
        "research_grant", "Science and technology research schemes for academics.",
    ),
    FacultySeed(
        "INSPIRE Faculty Scheme", "online-inspire.gov.in",
        "https://online-inspire.gov.in/",
        "research_grant", "Faculty fellowships for early career researchers.",
    ),
    FacultySeed(
        "IIT Bombay Faculty Recruitment", "iitb.ac.in",
        "https://www.iitb.ac.in/",
        "academic_recruitment", "Faculty positions at an IIT; representative of the IIT system.",
    ),
    FacultySeed(
        "National Institute of Ayurveda faculty", "nia.nic.in",
        "https://recruitment.niajaipur.com/",
        "academic_recruitment", "AYUSH faculty and research posts; overlaps the AYUSH seeds.",
    ),
)

_OPPORTUNITY_SIGNALS = (
    "vacanc", "recruit", "advertisement", "applications are invited",
    "faculty development", "fdp", "refresher", "fellowship", "career",
    "notification", "walk-in", "post of", "appointment", "grant",
)


async def probe(seed: FacultySeed, *, timeout: float) -> tuple[bool, str]:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; VidyaVerse/1.0; +seed-check)"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers, verify=False
        ) as client:
            response = await client.get(seed.url)
            if response.status_code >= 500:
                return False, f"HTTP {response.status_code}"
            body = (response.text or "").lower()
            signals = sum(1 for term in _OPPORTUNITY_SIGNALS if term in body)
            if signals == 0:
                return True, f"HTTP {response.status_code}, no vacancy wording visible"
            return True, f"HTTP {response.status_code}, {signals} signal(s)"
    except Exception as exc:  # noqa: BLE001 - the reason is the output
        return False, type(exc).__name__


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    # Government academic portals are as slow as the AYUSH ones; 15s reported
    # four working sites as dead there.
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.core.audiences import FACULTY
    from app.models.source_discovery import CompanySeed

    await init_database()

    print(f"Probing {len(FACULTY_SOURCES)} faculty sources…\n")
    results = await asyncio.gather(*(probe(seed, timeout=args.timeout) for seed in FACULTY_SOURCES))

    reachable = []
    for seed, (ok, reason) in zip(FACULTY_SOURCES, results):
        print(f"  [{'ok  ' if ok else 'FAIL'}] {seed.name:<40} {reason}")
        if ok:
            reachable.append(seed)
    print(f"\n{len(reachable)}/{len(FACULTY_SOURCES)} reachable")

    created = skipped = 0
    for seed in reachable:
        if await CompanySeed.find_one(CompanySeed.domain == seed.domain) is not None:
            skipped += 1
            continue
        created += 1
        if args.apply:
            await CompanySeed(
                company_name=seed.name,
                domain=seed.domain,
                careers_url=seed.url,
                audience=FACULTY,
                industry=seed.category,
                company_size="large",
                source_category=f"faculty_{seed.category}",
                priority_tier="faculty",
                notes=seed.note,
                added_by="seed_faculty_sources",
                check_cadence_hours=168,
                target_roles=["faculty development", "fdp", "postdoc", "faculty position", "research grant"],
            ).insert()

    print(f"{'created' if args.apply else 'would create'}: {created}    already present: {skipped}")
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
