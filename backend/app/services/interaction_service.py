from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from beanie import PydanticObjectId

from app.models.opportunity_interaction import OpportunityInteraction


class InteractionService:
    async def log_event(
        self,
        *,
        user_id: PydanticObjectId,
        opportunity_id: PydanticObjectId,
        interaction_type: str,
        ranking_mode: Optional[str] = None,
        query: Optional[str] = None,
    ) -> OpportunityInteraction:
        event = OpportunityInteraction(
            user_id=user_id,
            opportunity_id=opportunity_id,
            interaction_type=interaction_type,  # type: ignore[arg-type]
            ranking_mode=ranking_mode,  # type: ignore[arg-type]
            query=(query or None),
        )
        await event.insert()
        return event

    async def log_impressions(
        self,
        *,
        user_id: PydanticObjectId,
        opportunity_ids: Iterable[PydanticObjectId],
        ranking_mode: Optional[str],
        query: Optional[str] = None,
    ) -> int:
        inserted = 0
        for opportunity_id in opportunity_ids:
            await self.log_event(
                user_id=user_id,
                opportunity_id=opportunity_id,
                interaction_type="impression",
                ranking_mode=ranking_mode,
                query=query,
            )
            inserted += 1
        return inserted

    async def ctr_by_mode(self, days: int = 30) -> list[dict[str, Any]]:
        since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.created_at >= since,
        ).to_list()

        impressions: dict[str, int] = defaultdict(int)
        clicks: dict[str, int] = defaultdict(int)

        for interaction in interactions:
            mode = interaction.ranking_mode or "unknown"
            if interaction.interaction_type == "impression":
                impressions[mode] += 1
            elif interaction.interaction_type in {"click", "apply", "view"}:
                clicks[mode] += 1

        all_modes = sorted(set(impressions.keys()) | set(clicks.keys()))
        report: list[dict[str, Any]] = []
        for mode in all_modes:
            total_impressions = impressions.get(mode, 0)
            total_clicks = clicks.get(mode, 0)
            ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0
            report.append(
                {
                    "mode": mode,
                    "impressions": total_impressions,
                    "clicks": total_clicks,
                    "ctr": round(ctr, 6),
                }
            )

        return report


interaction_service = InteractionService()
