"""Give the Ayush domain a demand table, so the platform speaks its sponsor's field.

The problem statement is sponsored by the Ministry of Ayush and the All India
Institute of Ayurveda. The product was answering it with a curriculum signal
about machine learning and Java, which is a correct product pointed at the
wrong sector.

The demand side cannot be scraped. Thirty candidate sources were fetched and
read the way the extractor reads them - councils, national institutes,
manufacturers, wellness employers and NCS - and the best yield was seven rows,
two of which were navigation. Ayush publishes vacancies as PDF notices.

So the Ayush demand table is built from `app/services/ayush_standards.py`: the
competencies the sector's published standards require of the roles graduates
actually enter. The snapshot is written with basis="occupational_standard" and
carries the sentence the UI prints above it, so no reader can mistake it for a
scrape.

Dry run by default, per this repo's convention for anything that writes.

    python scripts/seed_ayush_domain.py            # report only
    python scripts/seed_ayush_domain.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

#: The domain string BAMS profiles carry. Matched case-insensitively downstream
#: via domain_key, which exists because profiles shout their domain and the
#: corpus does not.
AYUSH_DOMAIN = "Ayurveda and Ayush"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the snapshot (default: dry run)")
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.models.skill_assessment import SkillDemandSnapshot
    from app.services.sih_ayush_standards import DEMAND_BASIS, ROLES, demand_rows
    from app.services.skill_demand import domain_key

    await init_database()
    rows = demand_rows()

    print(f"Domain: {AYUSH_DOMAIN}")
    print(f"Basis:  occupational_standard")
    print()
    print(DEMAND_BASIS)
    print()
    print(f"{'competency':26} {'weight':>7} {'roles':>6}  taught in")
    print("-" * 92)
    for row in rows:
        taught = row["taught_in"] or "NOT IN THE CURRICULUM"
        print(f"  {str(row['skill']):24} {float(row['share']):7.2f} {int(row['roles_requiring']):>6}  {taught}")
    print()
    print(f"{len(ROLES)} graduate roles mapped: " + ", ".join(role.title for role in ROLES))
    print()

    existing = await SkillDemandSnapshot.find_one(
        SkillDemandSnapshot.domain_key == domain_key(AYUSH_DOMAIN)
    )
    print(f"Existing snapshot for this domain: {'yes' if existing else 'no'}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write it.")
        return 0

    snapshot = SkillDemandSnapshot(
        domain=AYUSH_DOMAIN,
        domain_key=domain_key(AYUSH_DOMAIN),
        skills=rows,
        basis="occupational_standard",
        basis_note=DEMAND_BASIS,
        # Deliberately zero. Nothing was analysed, and writing a count here
        # would put a posting-shaped number on a snapshot that never saw one.
        postings_analysed=0,
        postings_with_skills=0,
        corpus_version="ayush-standards-v1",
    )
    await snapshot.insert()
    print(f"\nWrote snapshot {snapshot.id} with {len(rows)} competencies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
