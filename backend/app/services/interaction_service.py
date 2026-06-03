from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
import uuid

from beanie import PydanticObjectId

from app.core.metrics import INTERACTION_EVENTS_TOTAL
from app.core.cache import cache_manager
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.traffic import TrafficType
from app.models.user_journey import UserJourney
from app.core.time import utc_now


VALID_RANKING_MODES = {"baseline", "semantic", "ml", "ab", "diversity"}
EVENT_ALIASES = {
    "view": "expand",
    "apply": "apply_complete",
    "shortlisted": "apply_complete",
    "interview": "apply_complete",
}
VALID_CANONICAL_EVENTS = {
    "impression",
    "click",
    "expand",
    "save",
    "share",
    "apply_start",
    "apply_complete",
    "skip",
    "dismiss",
    "rejected",
}
VALID_INTERACTION_TYPES = VALID_CANONICAL_EVENTS | set(EVENT_ALIASES.keys())
APPLY_LIKE_EVENTS = {"apply", "apply_start", "apply_complete", "shortlisted", "interview"}


def canonical_event_type(value: str | None) -> str:
    normalized = (value or "view").strip().lower() or "view"
    canonical = EVENT_ALIASES.get(normalized, normalized)
    return canonical if canonical in VALID_CANONICAL_EVENTS else "expand"


def funnel_event_type(*, interaction_type: str | None, event_type: str | None = None) -> str | None:
    raw = (interaction_type or "").strip().lower()
    canonical = canonical_event_type(event_type or raw)
    if canonical == "impression":
        return "impression"
    if canonical == "click":
        return "click"
    if canonical == "save":
        return "save"
    if canonical in {"apply_start", "apply_complete"} or raw in APPLY_LIKE_EVENTS:
        return "apply"
    if canonical in {"expand"} or raw == "view":
        return "view"
    return None


def object_id_or_none(value: Any) -> PydanticObjectId | None:
    try:
        return value if isinstance(value, PydanticObjectId) else PydanticObjectId(str(value))
    except Exception:
        return None


class SignalStrengthCalculator:
    BASE_REWARDS = {
        "impression": 0.0,
        "click": 0.2,
        "expand": 0.35,
        "save": 0.6,
        "share": 0.5,
        "apply_start": 0.75,
        "apply_complete": 1.0,
        "skip": -0.1,
        "dismiss": -0.1,
        "rejected": -0.1,
    }

    def normalize_event_type(self, value: str | None) -> str:
        return canonical_event_type(value)

    def reward(
        self,
        *,
        event_type: str | None,
        dwell_time_ms: Optional[int] = None,
        scroll_depth: Optional[float] = None,
    ) -> float:
        normalized = self.normalize_event_type(event_type)
        reward = float(self.BASE_REWARDS.get(normalized, 0.0))
        if dwell_time_ms is not None and int(dwell_time_ms) >= 30_000:
            reward = max(reward, 0.45)
        if scroll_depth is not None and float(scroll_depth) >= 90.0 and normalized in {"click", "expand"}:
            reward = max(reward, 0.45)
        return round(max(-1.0, min(1.0, reward)), 4)


class InteractionService:
    def __init__(self, signal_calculator: SignalStrengthCalculator | None = None) -> None:
        self.signal_calculator = signal_calculator or SignalStrengthCalculator()

    def normalize_ranking_mode(self, value: str | None) -> str | None:
        normalized = (value or "").strip().lower()
        return normalized if normalized in VALID_RANKING_MODES else None

    def normalize_traffic_type(self, value: str | None) -> str:
        normalized = (value or "real").strip().lower()
        return normalized if normalized in {"real", "simulated"} else "real"

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
        dwell_time_ms: Optional[int] = None,
        scroll_depth: Optional[float] = None,
        session_id: Optional[str] = None,
        cold_start: bool = False,
        traffic_type: TrafficType = "real",
    ) -> OpportunityInteraction:
        normalized_mode = self.normalize_ranking_mode(ranking_mode)
        normalized_key = (experiment_key or "none").strip().lower() or "none"
        normalized_variant = (experiment_variant or "none").strip().lower() or "none"
        normalized_type = (interaction_type or "unknown").strip().lower() or "unknown"
        event_type = self.signal_calculator.normalize_event_type(normalized_type)
        stored_interaction_type = normalized_type if normalized_type in VALID_INTERACTION_TYPES else event_type
        reward = self.signal_calculator.reward(
            event_type=event_type,
            dwell_time_ms=dwell_time_ms,
            scroll_depth=scroll_depth,
        )
        normalized_traffic = self.normalize_traffic_type(traffic_type)
        if INTERACTION_EVENTS_TOTAL is not None:
            INTERACTION_EVENTS_TOTAL.labels(
                interaction_type=event_type,
                ranking_mode=normalized_mode or "unknown",
                experiment_key=normalized_key,
                experiment_variant=normalized_variant,
                traffic_type=normalized_traffic,
            ).inc()

        event = OpportunityInteraction(
            user_id=user_id,
            opportunity_id=opportunity_id,
            interaction_type=stored_interaction_type,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            reward=reward,
            dwell_time_ms=dwell_time_ms,
            scroll_depth=scroll_depth,
            referrer_rank=rank_position,
            session_id=session_id,
            cold_start=bool(cold_start),
            ranking_mode=normalized_mode,  # type: ignore[arg-type]
            experiment_key=(experiment_key or None),
            experiment_variant=(experiment_variant or None),
            query=(query or None),
            model_version_id=(model_version_id or None),
            rank_position=rank_position,
            match_score=match_score,
            features=features,
            traffic_type=normalized_traffic,  # type: ignore[arg-type]
        )
        await event.insert()
        await self._update_journey(event=event, query=query)
        await cache_manager.invalidate_after_user_interaction(user_id=str(user_id))
        return event

    async def log_batch(
        self,
        *,
        user_id: PydanticObjectId,
        events: Iterable[dict[str, Any]],
        traffic_type: TrafficType = "real",
    ) -> list[OpportunityInteraction]:
        inserted: list[OpportunityInteraction] = []
        for payload in events:
            opportunity_id = object_id_or_none(payload.get("opportunity_id"))
            if not opportunity_id:
                continue
            inserted.append(
                await self.log_event(
                    user_id=user_id,
                    opportunity_id=opportunity_id,
                    interaction_type=str(payload.get("interaction_type") or payload.get("event_type") or "view"),
                    ranking_mode=payload.get("ranking_mode"),
                    experiment_key=payload.get("experiment_key"),
                    experiment_variant=payload.get("experiment_variant"),
                    query=payload.get("query"),
                    model_version_id=payload.get("model_version_id"),
                    rank_position=payload.get("rank_position"),
                    match_score=payload.get("match_score"),
                    features=payload.get("features"),
                    dwell_time_ms=payload.get("dwell_time_ms"),
                    scroll_depth=payload.get("scroll_depth"),
                    session_id=payload.get("session_id"),
                    cold_start=bool(payload.get("cold_start") or False),
                    traffic_type=traffic_type,
                )
            )
        return inserted

    async def _update_journey(self, *, event: OpportunityInteraction, query: Optional[str]) -> None:
        try:
            now = utc_now()
            session_id = event.session_id or await self._resolve_session_id(user_id=event.user_id, now=now)
            if not event.session_id:
                event.session_id = session_id
                await event.save()

            journey = await UserJourney.find_one(
                UserJourney.user_id == event.user_id,
                UserJourney.session_id == session_id,
            )
            if journey is None:
                journey = UserJourney(
                    user_id=event.user_id,
                    session_id=session_id,
                    started_at=now,
                    ended_at=now,
                    cold_start=bool(event.cold_start),
                )
                await journey.insert()

            opportunity_ids = list(journey.opportunity_ids or [])
            if all(str(item) != str(event.opportunity_id) for item in opportunity_ids):
                opportunity_ids.append(event.opportunity_id)

            search_queries = list(journey.search_queries or [])
            normalized_query = (query or "").strip()
            if normalized_query and normalized_query not in search_queries:
                search_queries.append(normalized_query)

            event_type = event.event_type or event.interaction_type
            path = list(journey.path or [])
            path.append(
                {
                    "interaction_id": str(event.id),
                    "opportunity_id": str(event.opportunity_id),
                    "event_type": event_type,
                    "reward": event.reward,
                    "rank_position": event.rank_position,
                    "dwell_time_ms": event.dwell_time_ms,
                    "scroll_depth": event.scroll_depth,
                    "created_at": event.created_at.isoformat(),
                }
            )

            pogo_sticking = bool(
                event_type in {"click", "expand"}
                and event.dwell_time_ms is not None
                and 0 <= int(event.dwell_time_ms) < 5_000
            )
            journey.opportunity_ids = opportunity_ids
            journey.search_queries = search_queries
            journey.path = path[-200:]
            journey.event_count = int(journey.event_count or 0) + 1
            journey.reward_sum = float(journey.reward_sum or 0.0) + float(event.reward or 0.0)
            journey.pogo_sticking_count = int(journey.pogo_sticking_count or 0) + (1 if pogo_sticking else 0)
            journey.cold_start = bool(journey.cold_start or event.cold_start)
            journey.ended_at = now
            journey.updated_at = now
            await journey.save()
        except Exception:
            return

    async def _resolve_session_id(self, *, user_id: PydanticObjectId, now: datetime) -> str:
        cutoff = now - timedelta(minutes=30)
        rows = (
            await UserJourney.find_many(
                UserJourney.user_id == user_id,
                UserJourney.ended_at >= cutoff,
            )
            .sort("-ended_at")
            .limit(1)
            .to_list()
        )
        if rows:
            return str(rows[0].session_id)
        return f"journey:{user_id}:{uuid.uuid4().hex}"

    async def log_impressions(
        self,
        *,
        user_id: PydanticObjectId,
        impressions: Iterable[dict[str, Any]],
        traffic_type: TrafficType = "real",
    ) -> int:
        inserted = 0
        for impression in impressions:
            opportunity_id = object_id_or_none(impression.get("opportunity_id"))
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
                dwell_time_ms=impression.get("dwell_time_ms"),
                scroll_depth=impression.get("scroll_depth"),
                session_id=impression.get("session_id"),
                cold_start=bool(impression.get("cold_start") or False),
                traffic_type=(impression.get("traffic_type") or traffic_type),
            )
            inserted += 1
        return inserted

    async def ctr_by_mode(self, days: int = 30, traffic_type: str = "all") -> list[dict[str, Any]]:
        since = utc_now() - timedelta(days=max(1, min(days, 365)))
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
            event_type = interaction.event_type or interaction.interaction_type
            if event_type == "impression":
                impressions[mode] += 1
            elif event_type == "click":
                clicks[mode] += 1
            elif event_type in {"apply", "apply_complete"}:
                applies[mode] += 1
            elif event_type == "save":
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
