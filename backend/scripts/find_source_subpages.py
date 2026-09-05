"""Find the page on a site that actually lists opportunities.

Qualification scores a source by what is on the URL it was given, and a cluster
of otherwise good sources land at 58-59 against a threshold of 60 for one
reason: they were seeded with a landing page. A ministry homepage is a homepage.
`opportunity_density` reports candidate_items=0 and it is right to.

The fix is mechanical and was proven by hand on CCRAS: repointing it from
`ccras.nic.in/` to `ccras.nic.in/recruitment-and-results/` took it from 58 and
rejected to 83.5 and qualified. This does that search for any source, rather
than leaving it as something someone remembers to do.

It crawls a source's page for links whose text or href suggests listings,
fetches each candidate, and scores it by how much opportunity wording it carries
compared to the page currently seeded. Only a clear improvement is proposed,
because a sub-page that is no better is churn with a plausible story attached.

Dry run by default.

    python scripts/find_source_subpages.py --status rejected
    python scripts/find_source_subpages.py --status rejected --apply --requalify
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)

# Words in a link that suggest it leads to listings rather than prose.
LINK_HINTS = (
    "vacanc", "recruit", "career", "job", "opportunit", "employment",
    "advertis", "notification", "tender", "scheme", "fellowship",
    "grant", "admission", "hiring", "openings", "apply", "circular",
)

# Words on the destination page that suggest it carries listings.
PAGE_SIGNALS = (
    "vacanc", "recruit", "advertisement", "applications are invited", "apply",
    "internship", "job", "career", "opportunit", "fellowship", "scholarship",
    "faculty development", "fdp", "refresher", "grant", "scheme",
    "notification", "walk-in", "post of", "appointment", "last date",
    "eligibility", "closing date",
)

# Anything below this many extra signals is not worth repointing a source for.
MIN_IMPROVEMENT = 3


@dataclass
class Candidate:
    url: str
    signals: int


async def _fetch(client, url: str) -> str:
    try:
        response = await client.get(url)
        if response.status_code >= 400:
            return ""
        return (response.text or "").lower()
    except Exception:  # noqa: BLE001 - a dead candidate is simply not a candidate
        return ""


def _score(body: str) -> int:
    return sum(1 for term in PAGE_SIGNALS if term in body)


async def best_subpage(base_url: str, *, timeout: float, max_candidates: int = 8):
    """Return (current_signals, best_candidate) for a source URL."""
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (compatible; VidyaVerse/1.0; +subpage-finder)"}
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=headers, verify=False
    ) as client:
        body = await _fetch(client, base_url)
        if not body:
            return 0, None
        current = _score(body)

        host = urlparse(base_url).netloc.lower()
        seen: set[str] = set()
        candidates: list[str] = []
        for link in HREF.findall(body):
            low = link.lower()
            if not any(hint in low for hint in LINK_HINTS):
                continue
            full = urljoin(base_url, link)
            # Same-site only. Following a link off-domain would repoint the
            # source at somebody else's site, which is worse than leaving it.
            if urlparse(full).netloc.lower() != host:
                continue
            if full in seen or full.rstrip("/") == base_url.rstrip("/"):
                continue
            seen.add(full)
            candidates.append(full)
            if len(candidates) >= max_candidates:
                break

        if not candidates:
            return current, None

        bodies = await asyncio.gather(*(_fetch(client, url) for url in candidates))
        scored = [Candidate(url, _score(text)) for url, text in zip(candidates, bodies) if text]
        if not scored:
            return current, None
        scored.sort(key=lambda c: -c.signals)
        return current, scored[0]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="rejected", help="source status to examine")
    parser.add_argument("--audience", default=None, help="limit to one audience")
    parser.add_argument("--apply", action="store_true", help="write the improved URLs")
    parser.add_argument("--requalify", action="store_true", help="re-run qualification after writing")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    from app.bootstrap import init_database
    from app.core.time import utc_now
    from app.models.source_discovery import DiscoveredSource

    await init_database()

    rows = await DiscoveredSource.find_many().to_list()
    targets = [
        row
        for row in rows
        if args.status in str(row.status).lower()
        and (not args.audience or getattr(row, "audience", "student") == args.audience)
    ][: args.limit]

    print(f"Examining {len(targets)} sources with status '{args.status}'…\n")
    improved: list[tuple[DiscoveredSource, str, int, int]] = []

    for source in targets:
        try:
            current, best = await best_subpage(source.url, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"  [err ] {source.domain:<28} {type(exc).__name__}")
            continue
        if best is None or best.signals - current < MIN_IMPROVEMENT:
            note = "no better sub-page found" if best is None else f"best +{best.signals - current}, not enough"
            print(f"  [keep] {source.domain:<28} {current} signals, {note}")
            continue
        print(f"  [FIX ] {source.domain:<28} {current} -> {best.signals} signals")
        print(f"         {best.url[:96]}")
        improved.append((source, best.url, current, best.signals))

    print(f"\n{len(improved)}/{len(targets)} have a better page")

    if not args.apply:
        print("\nDry run. Re-run with --apply to repoint them.")
        return 0

    from app.services.source_discovery import source_qualification_service

    for source, url, _before, _after in improved:
        source.url = url
        source.updated_at = utc_now()
        await source.save()

    print(f"repointed: {len(improved)}")

    if args.requalify:
        print("\nRe-qualifying…")
        for source, _url, _before, _after in improved:
            try:
                out = await source_qualification_service.qualify_source(source.id)
                status = str(out.status).split(".")[-1]
                print(f"  {source.domain:<28} {status:<11} score={out.qualification_score}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {source.domain:<28} ERROR {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
