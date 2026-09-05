"""Seed AYUSH institutions and Ayurveda industry as discovery sources.

Problem statement 26044 is sponsored by the Ministry of Ayush and the All India
Institute of Ayurveda, and the corpus had nothing from that world at all: 1,989
live postings, none of them AYUSH. That is not a gap in coverage so much as a
gap in the premise - a skill-gap engine derives "current industry requirements"
from the postings it holds, so with no AYUSH postings it cannot say anything
about an AYUSH student, however good the model is.

Every seed here is probed before it is written. The alternative is asserting a
list of domains from memory, and a seed pointing at a domain that does not
resolve fails silently: discovery marks it unreachable, retries it on a cadence,
and the source simply never produces anything while looking present in the
table. Probing turns that into a line of output at seed time.

Dry run by default, per this repo's convention for anything that writes.

    python scripts/seed_ayush_sources.py            # probe and report only
    python scripts/seed_ayush_sources.py --apply    # write the ones that respond
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
class AyushSeed:
    company_name: str
    domain: str
    careers_url: str
    industry: str
    company_size: str
    source_category: str
    notes: str


# Statutory bodies, national institutes and research councils. These are where
# AYUSH internships, fellowships and faculty positions are actually advertised.
INSTITUTIONS: tuple[AyushSeed, ...] = (
    AyushSeed(
        "Ministry of Ayush", "ayush.gov.in", "https://ayush.gov.in/",
        "government", "large", "ayush_institution",
        "Parent ministry for the problem statement; publishes vacancies and fellowships.",
    ),
    AyushSeed(
        "All India Institute of Ayurveda", "aiia.gov.in", "https://aiia.gov.in/",
        "government", "large", "ayush_institution",
        "The sponsoring institute for SIH problem statement 26044.",
    ),
    AyushSeed(
        "National Commission for Indian System of Medicine", "ncismindia.org",
        "https://ncismindia.org/", "government", "large", "ayush_institution",
        "Regulator for Ayurveda/Unani/Siddha education; sets the BAMS curriculum.",
    ),
    AyushSeed(
        "Central Council for Research in Ayurvedic Sciences", "ccras.nic.in",
        "https://ccras.nic.in/recruitment-and-results/", "government", "large", "ayush_institution",
        "Apex Ayurveda research body; recruits research officers and fellows.",
    ),
    AyushSeed(
        "Central Council for Research in Yoga and Naturopathy", "ccryn.gov.in",
        "https://ccryn.gov.in/", "government", "medium", "ayush_institution",
        "Yoga and naturopathy research posts.",
    ),
    AyushSeed(
        "Central Council for Research in Unani Medicine", "ccrum.res.in",
        "https://ccrum.res.in/", "government", "medium", "ayush_institution",
        "Unani research positions.",
    ),
    AyushSeed(
        "Central Council for Research in Homoeopathy", "ccrhindia.nic.in",
        "https://ccrhindia.nic.in/", "government", "medium", "ayush_institution",
        "Homoeopathy research positions.",
    ),
    AyushSeed(
        "National Institute of Ayurveda, Jaipur", "nia.nic.in", "https://recruitment.niajaipur.com/",
        "government", "large", "ayush_institution",
        "Deemed university; PG and research vacancies.",
    ),
    AyushSeed(
        "Institute of Teaching and Research in Ayurveda", "itra.edu.in",
        "https://itra.edu.in/", "government", "large", "ayush_institution",
        "Institute of National Importance at Jamnagar.",
    ),
    AyushSeed(
        "Morarji Desai National Institute of Yoga", "yogamdniy.nic.in",
        "https://yogamdniy.nic.in/vacancy", "government", "medium", "ayush_institution",
        "Yoga therapy and instructor roles.",
    ),
    AyushSeed(
        "National Medicinal Plants Board", "nmpb.nic.in", "https://nmpb.nic.in/",
        "government", "medium", "ayush_institution",
        "Medicinal plant research and cultivation projects.",
    ),
)

# The private side. This is where most BAMS and Ayurvedic pharmacy graduates are
# actually hired - quality control, formulation, pharmacovigilance, medical
# writing - which is precisely the employability the problem statement is about.
INDUSTRY: tuple[AyushSeed, ...] = (
    AyushSeed(
        "Dabur India", "dabur.com", "https://www.dabur.com/",
        "ayurveda_pharma", "large", "ayush_industry",
        "Largest Ayurvedic FMCG in India; R&D and QC roles.",
    ),
    AyushSeed(
        "Himalaya Wellness", "himalayawellness.in",
        "https://www.himalayawellness.in/pages/careers",
        "ayurveda_pharma", "large", "ayush_industry",
        "Herbal formulation and clinical research roles.",
    ),
    AyushSeed(
        "Baidyanath", "baidyanath.co", "https://www.baidyanath.co/",
        "ayurveda_pharma", "large", "ayush_industry",
        "Classical Ayurvedic manufacturing.",
    ),
    AyushSeed(
        "Kerala Ayurveda", "keralaayurveda.biz", "https://www.keralaayurveda.biz/",
        "ayurveda_pharma", "medium", "ayush_industry",
        "Manufacturing plus panchakarma clinical roles.",
    ),
    AyushSeed(
        "Charak Pharma", "charak.com", "https://www.charak.com/",
        "ayurveda_pharma", "medium", "ayush_industry",
        "Ayurvedic formulations; medical writing and QC.",
    ),
    AyushSeed(
        "The Arya Vaidya Pharmacy", "aryavaidyapharmacy.com",
        "https://www.aryavaidyapharmacy.com/", "ayurveda_pharma", "medium",
        "ayush_industry", "Traditional Kerala Ayurveda manufacturer and hospitals.",
    ),
    AyushSeed(
        "Patanjali Ayurved", "patanjaliayurved.org",
        "https://www.patanjaliayurved.org/", "ayurveda_pharma", "large",
        "ayush_industry", "Large-scale Ayurvedic manufacturing.",
    ),
    AyushSeed(
        "Sri Sri Tattva", "srisritattva.com", "https://www.srisritattva.com/",
        "ayurveda_pharma", "medium", "ayush_industry",
        "Ayurvedic products and wellness centres.",
    ),
)

ALL_SEEDS: tuple[AyushSeed, ...] = INSTITUTIONS + INDUSTRY


# Words that indicate a page actually advertises positions, rather than merely
# belonging to an organisation that has some.
_OPPORTUNITY_SIGNALS = (
    "vacanc",
    "recruit",
    "advertisement",
    "applications are invited",
    "walk-in",
    "walk in",
    "engagement",
    "post of",
    "appointment",
    "career",
    "fellowship",
    "job",
)


async def probe(seed: AyushSeed, *, timeout: float) -> tuple[bool, str]:
    """Does this source respond, and does it look like it advertises anything?

    The first version of this checked only that the host answered, which is the
    wrong property. Every seed passed, and then qualification rejected 14 of 16 -
    ayush.gov.in scored 58 against a threshold of 60 with
    `opportunity_density: candidate_items=0`, because a ministry homepage is a
    homepage. The probe had confirmed the sites were up, which nobody doubted,
    and said nothing about whether they carried vacancies.

    So the content check is the point of this function now. A seed that responds
    but shows no sign of advertising positions is reported as thin, because the
    pipeline will reject it and the operator should know that here rather than
    from a status column days later.
    """
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; VidyaVerse/1.0; +seed-check)"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers, verify=False
        ) as client:
            response = await client.get(seed.careers_url)
            # 403/401 still proves the host exists and serves; discovery has
            # stealth fetchers for those. A DNS or connect failure does not.
            if response.status_code >= 500:
                return False, f"HTTP {response.status_code}"
            body = (response.text or "").lower()
            signals = sum(1 for term in _OPPORTUNITY_SIGNALS if term in body)
            if signals == 0:
                # Not a hard failure: many government portals build their menus
                # in JavaScript, which the render-capable scraper sees and this
                # plain fetch does not.
                return True, f"HTTP {response.status_code}, no vacancy wording visible"
            return True, f"HTTP {response.status_code}, {signals} vacancy signal(s)"
    except Exception as exc:  # noqa: BLE001 - the reason is the output
        return False, type(exc).__name__


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write verified seeds (default: dry run)")
    # Government AYUSH portals are genuinely slow: at 15s, four working
    # sources (ayush.gov.in, nia.nic.in, yogamdniy.nic.in, nmpb.nic.in)
    # all reported as dead. A probe that is too impatient produces the
    # same silent gap it exists to prevent.
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--include-unreachable", action="store_true",
                        help="write seeds that did not respond (not recommended)")
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.models.source_discovery import CompanySeed

    await init_database()

    print(f"Probing {len(ALL_SEEDS)} AYUSH sources…\n")
    results = await asyncio.gather(*(probe(seed, timeout=args.timeout) for seed in ALL_SEEDS))

    reachable: list[AyushSeed] = []
    for seed, (ok, reason) in zip(ALL_SEEDS, results):
        mark = "ok  " if ok else "FAIL"
        print(f"  [{mark}] {seed.company_name:<52} {reason}")
        if ok:
            reachable.append(seed)

    print(f"\n{len(reachable)}/{len(ALL_SEEDS)} reachable")

    to_write = reachable if not args.include_unreachable else list(ALL_SEEDS)
    created = 0
    skipped = 0
    for seed in to_write:
        existing = await CompanySeed.find_one(CompanySeed.domain == seed.domain)
        if existing is not None:
            skipped += 1
            continue
        if args.apply:
            await CompanySeed(
                company_name=seed.company_name,
                domain=seed.domain,
                careers_url=seed.careers_url,
                industry=seed.industry,
                company_size=seed.company_size,
                source_category=seed.source_category,
                priority_tier="ayush",
                notes=seed.notes,
                added_by="seed_ayush_sources",
                # Government vacancy pages move slowly; weekly is plenty and
                # keeps the scrape budget for sources that actually churn.
                check_cadence_hours=168,
                target_roles=["internship", "0-1 years", "early career", "fellowship"],
            ).insert()
        created += 1

    verb = "created" if args.apply else "would create"
    print(f"{verb}: {created}    already present: {skipped}")
    if not args.apply:
        print("\nDry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
