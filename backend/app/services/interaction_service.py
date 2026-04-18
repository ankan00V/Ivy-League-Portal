from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from beanie import PydanticObjectId

from app.core.metrics import INTERACTION_EVENTS_TOTAL
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.traffic import TrafficType


class InteractionService:
    def _traffic_type_matches(
        self,
        *,
        event_traffic_type: Optional[str],
        event_experiment_key: Optional[str],
        filter_traffic_type: str,
    ) -> bool:
        normalized_filter = (filter_traffic_type or "all").strip().lower()
        if normalized_filter == "all":
            return True

        normalized_value = (event_traffic_type or "").strip().lower()
        if normalized_filter == "real":
            # Backward-compatible: missing traffic_type is treated as real.
            return normalized_value in {"", "real"}

        if normalized_filter == "simulated":
            if normalized_value == "simulated":
                return True
            # Backward-compatible inference for legacy simulation runs.
            key = (event_experiment_key or "").strip().lower()
            return "sim" in key

        return False

    async def log_event(
        self,
        *,
        user_id: PydanticObjectId,
        opportunity_id: PydanticObjectId,
        interaction_type: str,
        ranking_mode: Optional[str] = None,
        experiment_key: Optional[str] = None,
        experiment_variant: Optional[str] = None,
        query: Optional[str] = None,
        model_version_id: Optional[str] = None,
        rank_position: Optional[int] = None,
        match_score: Optional[float] = None,
        features: Optional[dict[str, Any]] = None,
        traffic_type: TrafficType = "real",
    ) -> OpportunityInteraction:
        normalized_mode = (ranking_mode or "unknown").strip().lower() or "unknown"
        normalized_key = (experiment_key or "none").strip().lower() or "none"
        normalized_variant = (experiment_variant or "none").strip().lower() or "none"
        normalized_type = (interaction_type or "unknown").strip().lower() or "unknown"
        normalized_traffic = (traffic_type or "real").strip().lower() or "real"
        if INTERACTION_EVENTS_TOTAL is not None:
            INTERACTION_EVENTS_TOTAL.labels(
                interaction_type=normalized_type,
                ranking_mode=normalized_mode,
                experiment_key=normalized_key,
                experiment_variant=normalized_variant,
                traffic_type=normalized_traffic,
            ).inc()

        event = OpportunityInteraction(
            user_id=user_id,
            opportunity_id=opportunity_id,
            interaction_type=interaction_type,  # type: ignore[arg-type]
            ranking_mode=ranking_mode,  # type: ignore[arg-type]
            experiment_key=(experiment_key or None),
            experiment_variant=(experiment_variant or None),
            query=(query or None),
            model_version_id=(model_version_id or None),
            rank_position=rank_position,
            match_score=match_score,
            features=features,
            traffic_type=traffic_type,
        )
        await event.insert()
        return event

    async def log_impressions(
        self,
        *,
        user_id: PydanticObjectId,
        impressions: Iterable[dict[str, Any]],
        traffic_type: TrafficType = "real",
    ) -> int:
        inserted = 0
        for impression in impressions:
            opportunity_id = impression.get("opportunity_id")
            if not opportunity_id:
                continue
            await self.log_event(
                user_id=user_id,
                opportunity_id=opportunity_id,
                interaction_type="impression",
                ranking_mode=impression.get("ranking_mode"),
                experiment_key=impression.get("experiment_key"),
                experiment_variant=impression.get("experiment_variant"),
                query=impression.get("query"),
                model_version_id=impression.get("model_version_id"),
                rank_position=impression.get("rank_position"),
                match_score=impression.get("match_score"),
                features=impression.get("features"),
                traffic_type=(impression.get("traffic_type") or traffic_type),
            )
            inserted += 1
        return inserted

    async def ctr_by_mode(self, days: int = 30, traffic_type: str = "all") -> list[dict[str, Any]]:
        since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.created_at >= since,
        ).to_list()

        impressions: dict[str, int] = defaultdict(int)
        clicks: dict[str, int] = defaultdict(int)
        applies: dict[str, int] = defaultdict(int)
        saves: dict[str, int] = defaultdict(int)

        for interaction in interactions:
            if not self._traffic_type_matches(
                event_traffic_type=getattr(interaction, "traffic_type", None),
                event_experiment_key=getattr(interaction, "experiment_key", None),
                filter_traffic_type=traffic_type,
            ):
                continue
            mode = interaction.ranking_mode or "unknown"
            if interaction.interaction_type == "impression":
                impressions[mode] += 1
            elif interaction.interaction_type == "click":
                clicks[mode] += 1
            elif interaction.interaction_type == "apply":
                applies[mode] += 1
            elif interaction.interaction_type == "save":
                saves[mode] += 1

        all_modes = sorted(set(impressions.keys()) | set(clicks.keys()) | set(applies.keys()) | set(saves.keys()))
        report: list[dict[str, Any]] = []
        for mode in all_modes:
            total_impressions = impressions.get(mode, 0)
            total_clicks = clicks.get(mode, 0)
            total_applies = applies.get(mode, 0)
            total_saves = saves.get(mode, 0)

            ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0
            apply_rate = (total_applies / total_impressions) if total_impressions > 0 else 0.0
            save_rate = (total_saves / total_impressions) if total_impressions > 0 else 0.0
            report.append(
                {
                    "mode": mode,
                    "impressions": total_impressions,
                    "clicks": total_clicks,
                    "applies": total_applies,
                    "saves": total_saves,
                    "ctr": round(ctr, 6),
                    "apply_rate": round(apply_rate, 6),
                    "save_rate": round(save_rate, 6),
                }
            )

        return report

    async def lift_vs_baseline(
        self,
        *,
        days: int = 30,
        baseline_mode: str = "baseline",
        traffic_type: str = "all",
    ) -> dict[str, Any]:
        rows = await self.ctr_by_mode(days=days, traffic_type=traffic_type)
        baseline = next((row for row in rows if row.get("mode") == baseline_mode), None) or {}

        def _lift(value: float, baseline_value: float) -> Optional[float]:
            if baseline_value <= 0:
                return None
            return (value - baseline_value) / baseline_value

        baseline_ctr = float(baseline.get("ctr") or 0.0)
        baseline_apply = float(baseline.get("apply_rate") or 0.0)
        baseline_save = float(baseline.get("save_rate") or 0.0)

        enriched: list[dict[str, Any]] = []
        for row in rows:
            ctr = float(row.get("ctr") or 0.0)
            apply_rate = float(row.get("apply_rate") or 0.0)
            save_rate = float(row.get("save_rate") or 0.0)
            enriched.append(
                {
                    **row,
                    "lift": {
                        "ctr": None if row.get("mode") == baseline_mode else _lift(ctr, baseline_ctr),
                        "apply_rate": None if row.get("mode") == baseline_mode else _lift(apply_rate, baseline_apply),
                        "save_rate": None if row.get("mode") == baseline_mode else _lift(save_rate, baseline_save),
                    },
                }
            )

        return {
            "days": int(max(1, min(days, 365))),
            "baseline_mode": baseline_mode,
            "traffic_type": (traffic_type or "all").strip().lower() or "all",
            "baseline": baseline,
            "modes": enriched,
        }


interaction_service = InteractionService()
