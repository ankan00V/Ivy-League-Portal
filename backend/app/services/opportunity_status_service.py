from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Optional

import httpx

from app.core.time import as_utc_aware, utc_now
from app.models.opportunity import Opportunity

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
        url = str(getattr(opportunity, "url", "") or "").strip()
        if not url:
            return "unknown"
        try:
            async with httpx.AsyncClient(timeout=max(1.0, float(timeout_seconds)), follow_redirects=True) as client:
                response = await client.head(url)
                if response.status_code in {405, 403}:
                    response = await client.get(url)
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
