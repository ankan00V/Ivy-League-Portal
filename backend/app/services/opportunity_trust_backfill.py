from __future__ import annotations

from typing import Any

from app.models.opportunity import Opportunity
from app.services.opportunity_trust import apply_trust_assessment_preserving_review, assess_opportunity_trust


async def backfill_opportunity_trust(*, batch_size: int = 200, limit: int | None = None) -> dict[str, Any]:
    safe_batch_size = max(1, min(int(batch_size), 1000))
    remaining = None if limit is None else max(0, int(limit))
    skip = 0

    totals = {
        "scanned": 0,
        "updated": 0,
        "verified": 0,
        "needs_review": 0,
        "blocked": 0,
        "unreviewed": 0,
    }

    while True:
        current_batch_size = safe_batch_size if remaining is None else min(safe_batch_size, remaining)
        if current_batch_size <= 0:
            break

        rows = await Opportunity.find_many().sort("+created_at").skip(skip).limit(current_batch_size).to_list()
        if not rows:
            break

        for row in rows:
            totals["scanned"] += 1
            assessment = assess_opportunity_trust(row)

            changed = (
                str(getattr(row, "trust_status", "") or "") != assessment.trust_status
                or int(getattr(row, "trust_score", 0) or 0) != assessment.trust_score
                or int(getattr(row, "risk_score", 0) or 0) != assessment.risk_score
                or list(getattr(row, "risk_reasons", []) or []) != assessment.risk_reasons
                or list(getattr(row, "verification_evidence", []) or []) != assessment.verification_evidence
            )
            if changed:
                apply_trust_assessment_preserving_review(row, assessment)
                await row.save()
                totals["updated"] += 1

            totals[assessment.trust_status] = int(totals.get(assessment.trust_status, 0)) + 1

        skip += len(rows)
        if remaining is not None:
            remaining -= len(rows)

    return totals
