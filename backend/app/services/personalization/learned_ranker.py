from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.services.model_artifact_service import model_artifact_service

from app.services.personalization.feature_builder import RankerFeatures


@dataclass
class RankerResult:
    score: float
    model: str
    loaded: bool


@dataclass(frozen=True)
class FeatureImportanceItem:
    feature: str
    importance: float


class LearnedRanker:
    """
    Lightweight wrapper around a LightGBM/XGBoost model for online scoring.

    The server stays functional even when the ML deps/model file are missing:
    - If the model cannot be loaded, callers should fall back to heuristics.
    """

    def __init__(self) -> None:
        self._feature_names: list[str] | None = None
        self._booster = None
        self._model_kind: str | None = None
        self._loaded_path: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._booster is not None and bool(self._feature_names)

    def reload_if_needed(self) -> None:
        if not getattr(settings, "LEARNED_RANKER_ENABLED", False):
            return

        configured_uri = model_artifact_service.resolve_learned_ranker_uri()
        model_path = None
        if configured_uri:
            try:
                synced = model_artifact_service.sync_artifact(
                    uri=configured_uri,
                    expected_sha256=model_artifact_service.expected_checksum(),
                )
                model_path = Path(synced.local_path)
            except Exception:
                model_path = None
        if model_path is None:
            fallback = str(getattr(settings, "LEARNED_RANKER_MODEL_PATH", "") or "").strip()
            model_path = Path(fallback) if fallback else None
        if not model_path:
            return
        if not model_path.exists():
            return

        path_str = str(model_path.resolve())
        if self._loaded_path == path_str and self._booster is not None:
            return

        # Load LightGBM first (preferred), fall back to XGBoost.
        booster = None
        model_kind = None
        feature_names: list[str] | None = None

        try:
            import lightgbm as lgb  # type: ignore

            booster = lgb.Booster(model_file=path_str)
            feature_names = list(booster.feature_name())
            model_kind = "lightgbm"
        except Exception:
            booster = None

        if booster is None:
            try:
                import xgboost as xgb  # type: ignore

                booster = xgb.Booster()
                booster.load_model(path_str)
                # XGBoost model may not store feature names reliably; assume training used fixed ordering.
                feature_names = list(getattr(settings, "LEARNED_RANKER_FEATURES", []) or [])
                model_kind = "xgboost"
            except Exception:
                booster = None

        if booster is None:
            return

        self._booster = booster
        self._model_kind = model_kind
        self._feature_names = feature_names or []
        self._loaded_path = path_str

    def score(self, features: RankerFeatures) -> Optional[RankerResult]:
        self.reload_if_needed()
        if not self.is_loaded:
            return None

        assert self._feature_names is not None
        vector = features.as_ordered_vector(self._feature_names)

        try:
            if self._model_kind == "lightgbm":
                # LightGBM expects 2D.
                pred = float(self._booster.predict([vector])[0])  # type: ignore[union-attr]
            else:
                import numpy as np

                dmat = __import__("xgboost").DMatrix(np.asarray([vector], dtype=float), feature_names=self._feature_names)
                pred = float(self._booster.predict(dmat)[0])  # type: ignore[union-attr]
        except Exception:
            return None

        return RankerResult(score=pred, model=self._model_kind or "unknown", loaded=True)

    def feature_importance(self, *, top_k: int = 8) -> list[FeatureImportanceItem]:
        self.reload_if_needed()
        if not self.is_loaded:
            return []

        safe_top_k = max(1, min(int(top_k), 30))
        names = list(self._feature_names or [])
        if not names:
            return []

        scored: list[tuple[str, float]] = []
        try:
            if self._model_kind == "lightgbm":
                gains = list(self._booster.feature_importance(importance_type="gain"))  # type: ignore[union-attr]
                for idx, name in enumerate(names):
                    if idx >= len(gains):
                        break
                    value = float(gains[idx] or 0.0)
                    if value > 0:
                        scored.append((name, value))
            else:
                score_map = dict(self._booster.get_score(importance_type="gain"))  # type: ignore[union-attr]
                for name in names:
                    value = float(score_map.get(name) or 0.0)
                    if value > 0:
                        scored.append((name, value))
        except Exception:
            return []

        scored.sort(key=lambda row: row[1], reverse=True)
        return [
            FeatureImportanceItem(feature=name, importance=round(float(value), 6))
            for name, value in scored[:safe_top_k]
        ]


learned_ranker = LearnedRanker()
