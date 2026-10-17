from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Optional

import httpx

from app.core.time import as_utc_aware, utc_now
from app.core.url_guard import assert_public_http_url
from app.models.opportunity import Opportunity

logger = logging.getLogger(__name__)

OpportunityStatus = Literal["active", "closing_soon", "expired", "filled", "removed"]


@dataclass(frozen=True)
class OpportunityStatusRefreshReport:
    processed: int
    updated: int
    expired: int
    closing_soon: int
    active: int
    liveness_checked: int

    def model_dump(self) -> dict[str, int]:
        return {
            "processed": self.processed,
            "updated": self.updated,
            "expired": self.expired,
            "closing_soon": self.closing_soon,
            "active": self.active,
            "liveness_checked": self.liveness_checked,
        }



def _peer_is_public(response: Any) -> bool:
    """Was the socket we actually reached a public address?

    The pre-flight check resolves the hostname, then httpx resolves it again to
    connect. Between those two lookups a hostile resolver can answer once with a
    public address and once with 169.254.169.254 - classic DNS rebinding, and
    the reason a name-based check alone is not a guarantee.

    So the peer is re-checked after connecting, from the socket rather than from
    DNS. A request has already been sent by then, which is why this is a second
    line rather than the first: the verdict is discarded, nothing about the
    response is read, and the row keeps its previous status.

    Transports that expose no socket return True. This is a defence in depth on
    top of the pre-flight check, not a reason to fail every check when the
    extension is missing.
    """
    stream = (getattr(response, "extensions", None) or {}).get("network_stream")
    if stream is None:
        return True
    try:
        peer = stream.get_extra_info("server_addr")
    except Exception:
        return True
    if not peer:
        return True
    host = peer[0] if isinstance(peer, (tuple, list)) else peer
    try:
        address = ipaddress.ip_address(str(host).strip("[]"))
    except ValueError:
        return True
    if address.is_global:
        return True
    logger.warning("liveness check aborted: connection resolved to non-public address %s", address)
    return False


class OpportunityStatusService:
    closing_soon_days = 7
    freshness_half_life_days = 14.0

    def resolve_status(self, opportunity: Any) -> OpportunityStatus:
        lifecycle = str(getattr(opportunity, "lifecycle_status", "published") or "published").strip().lower()
        if lifecycle in {"closed", "filled"}:
            return "filled"
        if lifecycle in {"removed", "deleted"}:
            return "removed"

        now = utc_now()
        deadline = as_utc_aware(getattr(opportunity, "deadline", None))
        if deadline is not None:
            if deadline < now:
                return "expired"
            if deadline <= now + timedelta(days=self.closing_soon_days):
                return "closing_soon"
        return "active"

    def freshness_score(self, opportunity: Any) -> float:
        now = utc_now()
        latest = as_utc_aware(
            getattr(opportunity, "last_seen_at", None)
            or getattr(opportunity, "updated_at", None)
            or getattr(opportunity, "created_at", None)
        )
        if latest is None:
            return 0.25
        age_days = max(0.0, (now - latest).total_seconds() / 86_400.0)
        score = 2.0 ** (-age_days / self.freshness_half_life_days)
        deadline = as_utc_aware(getattr(opportunity, "deadline", None))
        if deadline is not None and deadline < now:
            score *= 0.1
        return round(max(0.0, min(1.0, score)), 4)

    async def check_url_liveness(self, opportunity: Opportunity, *, timeout_seconds: float = 6.0) -> str:
        """Ask whether a listing's link still resolves, without becoming a probe.

        This runs unattended against whatever URLs the corpus happens to hold,
        including rows from automatically discovered sources, so the address is
        untrusted input even though no person typed it. Two things keep it from
        being a server-side request forgery primitive:

        The destination is resolved and checked before the request, so a URL
        that points at loopback, RFC1918 or the cloud metadata range never gets
        fetched. `source_discovery` already guards its own fetches this way; the
        liveness sweep reached arbitrary stored URLs without it.

        Redirects are not followed. Following them hands the decision back to
        the remote host, which can answer a perfectly public URL with a 302 to
        169.254.169.254 and walk straight past the check above. A 3xx still
        counts as alive: the posting resolved to something, which is all this
        sweep is asking.

        A URL that fails the check returns "unknown" rather than "dead". It was
        never verified, and only 404/410 is allowed to retire a listing.
        """
        url = str(getattr(opportunity, "url", "") or "").strip()
        if not url:
            return "unknown"
        try:
            # getaddrinfo blocks. Inside an async sweep of 250 URLs that stalls
            # the whole event loop, including the request handlers sharing it.
            await asyncio.to_thread(assert_public_http_url, url)
        except Exception:
            logger.warning("liveness check skipped: %s is not a public http(s) target", url[:120])
            return "unknown"
        try:
            async with httpx.AsyncClient(
                timeout=max(1.0, float(timeout_seconds)), follow_redirects=False
            ) as client:
                response = await client.head(url)
                if not _peer_is_public(response):
                    return "unknown"
                if response.status_code in {405, 403}:
                    response = await client.get(url)
                    if not _peer_is_public(response):
                        return "unknown"
            if 200 <= int(response.status_code) < 400:
                return "alive"
            if int(response.status_code) in {404, 410}:
                return "dead"
            return "error"
        except Exception:
            return "error"

    async def refresh(
        self,
        *,
        limit: int = 2000,
        check_liveness: bool = False,
        liveness_limit: int = 50,
    ) -> OpportunityStatusRefreshReport:
        rows = await Opportunity.find_many().sort("-updated_at").limit(max(1, int(limit))).to_list()
        updated = 0
        expired = 0
        closing_soon = 0
        active = 0
        liveness_checked = 0
        now = utc_now()

        # Who gets the liveness budget, decided before the loop rather than by
        # whoever comes first in it.
        #
        # The page is ordered by -updated_at, so walking it and checking the
        # first `liveness_limit` rows spends the whole budget on the most
        # recently touched listings - the ones a scraper just confirmed. The
        # rows that need checking are the opposite ones: 1,347 of 2,587 active
        # listings have not been seen by any scraper in over 30 days, most from
        # one-off company career-page scrapes that will never run again, and
        # 81% carry no deadline, so nothing else can ever retire them. Ordered
        # by -updated_at they sit at the bottom and were never reached.
        #
        # Least-recently-verified first, never-verified before that, which is
        # the order that converges: every row gets checked once before any row
        # is checked twice.
        liveness_queue: set[int] = set()
        if check_liveness and int(liveness_limit) > 0:
            def _checked_at_key(row: Opportunity) -> tuple[int, float]:
                checked = as_utc_aware(getattr(row, "url_last_checked_at", None))
                if checked is None:
                    return (0, 0.0)
                return (1, checked.timestamp())

            eligible = [
                row
                for row in rows
                if not getattr(row, "url_last_checked_at", None)
                or as_utc_aware(getattr(row, "url_last_checked_at", None)) < now - timedelta(days=1)
            ]
            eligible.sort(key=_checked_at_key)
            liveness_queue = {id(row) for row in eligible[: max(0, int(liveness_limit))]}

        for row in rows:
            status = self.resolve_status(row)
            freshness = self.freshness_score(row)
            if status == "expired":
                expired += 1
            elif status == "closing_soon":
                closing_soon += 1
            elif status == "active":
                active += 1

            liveness_status: Optional[str] = None
            if id(row) in liveness_queue:
                liveness_status = await self.check_url_liveness(row)
                liveness_checked += 1
                if liveness_status == "dead":
                    status = "removed"

            changed = False
            if getattr(row, "opportunity_status", None) != status:
                row.opportunity_status = status
                changed = True
            if abs(float(getattr(row, "freshness_score", 0.0) or 0.0) - freshness) > 0.0001:
                row.freshness_score = freshness
                changed = True
            if liveness_status is not None:
                row.url_liveness_status = liveness_status
                row.url_last_checked_at = now
                changed = True
            if changed:
                row.lifecycle_updated_at = now
                await row.save()
                updated += 1

        return OpportunityStatusRefreshReport(
            processed=len(rows),
            updated=updated,
            expired=expired,
            closing_soon=closing_soon,
            active=active,
            liveness_checked=liveness_checked,
        )


opportunity_status_service = OpportunityStatusService()
