from __future__ import annotations

import json
from typing import Iterable

from app.core.config import settings
from app.core.metrics import ONLINE_FEATURE_PUBLISH_TOTAL
from app.core.redis import get_redis
from app.core.time import utc_now
from app.models.feature_store_row import FeatureStoreRow


class OnlineFeatureService:
    def _enabled(self) -> bool:
        return bool(settings.ONLINE_FEATURES_PUBLISH_ENABLED)

    def _feature_key(self, *, user_id: str, opportunity_id: str) -> str:
        prefix = str(settings.ONLINE_FEATURES_KEY_PREFIX or "vidyaverse:features").strip().rstrip(":")
        return f"{prefix}:user:{user_id}:opportunity:{opportunity_id}"

    def _user_index_key(self, *, user_id: str) -> str:
        prefix = str(settings.ONLINE_FEATURES_KEY_PREFIX or "vidyaverse:features").strip().rstrip(":")
        return f"{prefix}:user:{user_id}:latest"

    def _serialize_row(self, row: FeatureStoreRow) -> bytes:
        payload = {
            "row_key": row.row_key,
            "date": row.date,
            "user_id": row.user_id,
            "opportunity_id": row.opportunity_id,
            "ranking_mode": row.ranking_mode,
            "experiment_key": row.experiment_key,
            "experiment_variant": row.experiment_variant,
            "traffic_type": row.traffic_type,
            "rank_position": row.rank_position,
            "match_score": row.match_score,
            "features": dict(row.features or {}),
            "labels": dict(row.labels or {}),
            "source_event_id": row.source_event_id,
            "updated_at": (row.updated_at or utc_now()).isoformat(),
        }
        return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

    async def publish_rows(self, rows: Iterable[FeatureStoreRow]) -> int:
        if not self._enabled():
            return 0
        redis = get_redis()
        if redis is None:
            if ONLINE_FEATURE_PUBLISH_TOTAL is not None:
                ONLINE_FEATURE_PUBLISH_TOTAL.labels(target="redis", status="skipped").inc()
            return 0

        safe_ttl = max(60, int(settings.ONLINE_FEATURES_TTL_SECONDS))
        published = 0
        async with redis.pipeline(transaction=False) as pipe:
            for row in rows:
                user_id = str(row.user_id or "").strip()
                opportunity_id = str(row.opportunity_id or "").strip()
                if not user_id or not opportunity_id:
                    continue
                feature_key = self._feature_key(user_id=user_id, opportunity_id=opportunity_id)
                user_index_key = self._user_index_key(user_id=user_id)
                payload = self._serialize_row(row)
                pipe.set(feature_key, payload, ex=safe_ttl)
                pipe.hset(user_index_key, opportunity_id, payload)
                pipe.expire(user_index_key, safe_ttl)
                published += 1
            if published > 0:
                await pipe.execute()

        if ONLINE_FEATURE_PUBLISH_TOTAL is not None:
            ONLINE_FEATURE_PUBLISH_TOTAL.labels(target="redis", status="ok").inc(published)
        return published


online_feature_service = OnlineFeatureService()
