"""Retire rows that are a website's navigation rather than an opportunity.

IIT Bombay's careers page promoted 73 rows titled "Placements", "Donate",
"CSR", "Institute magazines" and "Director's Message". The listing selector
these templates fall back to matches every `<li>` on a page, and on a site with
no job markup the only thing that matches is the menu.

The extraction fix is `strip_page_chrome` plus `looks_like_opportunity`. This
retires what the old code already wrote, because a feed full of a university's
menu is worse than an empty one: an empty feed says "nothing yet" and this says
"apply to Donate".

Rows retire via opportunity_status="removed", never a hard delete - the repo's
rule, and the right one here, because a row wrongly retired can be brought back
and a deleted one cannot.

Dry run by default.

    python scripts/retire_navigation_opportunities.py            # report only
    python scripts/retire_navigation_opportunities.py --apply
    python scripts/retire_navigation_opportunities.py --audience faculty
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="retire the rows (default: dry run)")
    parser.add_argument("--audience", default=None, help="limit to one audience")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.core.time import utc_now
    from app.models.opportunity import Opportunity
    from app.services.source_discovery import (
        is_navigation_label,
        is_process_notice,
        looks_like_opportunity,
    )

    await init_database()

    query = [Opportunity.opportunity_status == "active"]
    if args.audience:
        query.append(Opportunity.audience == args.audience)
    rows = await Opportunity.find_many(*query).limit(args.limit).to_list()

    doomed = []
    for row in rows:
        audience = str(getattr(row, "audience", None) or "student")
        haystack = f"{row.title} {getattr(row, 'description', '') or ''}"
        # Judged by the same two rules extraction now applies, so this script
        # and the pipeline can never disagree about what a posting is.
        if (
            is_navigation_label(row.title)
            or is_process_notice(row.title)
            or not looks_like_opportunity(haystack, audience=audience)
        ):
            doomed.append(row)

    by_audience: dict[str, int] = {}
    for row in doomed:
        key = str(getattr(row, "audience", None) or "student")
        by_audience[key] = by_audience.get(key, 0) + 1

    print(f"Scanned {len(rows)} active opportunities.")
    print(f"Would retire {len(doomed)}: {by_audience or '{}'}")
    print()
    for row in doomed[:15]:
        print(f"  [{str(getattr(row, 'audience', '?')):11}] {str(row.title)[:70]:<70} <- {str(row.university)[:26]}")
    if len(doomed) > 15:
        print(f"  ... and {len(doomed) - 15} more")
    print()

    if not args.apply:
        print("Dry run. Re-run with --apply to retire them.")
        return 0

    retired = 0
    for row in doomed:
        row.opportunity_status = "removed"
        row.updated_at = utc_now()
        await row.save()
        retired += 1
    print(f"Retired {retired} row(s) as opportunity_status='removed'. None were deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
