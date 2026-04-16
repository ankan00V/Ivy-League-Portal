from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport
from app.models.ranking_model_version import RankingModelVersion
from app.models.user import User
from app.services.mlops.drift_service import drift_service
from app.services.mlops.retraining_service import retraining_service
from app.services.ranking_model_service import ranking_model_service

router = APIRouter()


class RetrainRequest(BaseModel):
    lookback_days: int = Field(default=settings.MLOPS_RETRAIN_LOOKBACK_DAYS, ge=1, le=365)
    label_window_hours: int = Field(default=settings.MLOPS_LABEL_WINDOW_HOURS, ge=1, le=24 * 30)
    min_rows: int = Field(default=settings.MLOPS_MIN_TRAINING_ROWS, ge=50, le=5_000_000)
    grid_step: float = Field(default=settings.MLOPS_TRAIN_GRID_STEP, ge=0.01, le=0.25)
    auto_activate: bool = Field(default=settings.MLOPS_AUTO_ACTIVATE)
    activation_policy: str = Field(default=settings.MLOPS_ACTIVATION_POLICY)
    min_auc_gain_for_activation: float = Field(default=settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN, ge=-1.0, le=1.0)
    min_positive_rate_for_activation: float = Field(default=settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE, ge=0.0, le=1.0)
    max_weight_shift_for_activation: float = Field(default=settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT, ge=0.0, le=2.0)
    notes: Optional[str] = None


class ModelVersionResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    weights: dict[str, float]
    metrics: dict[str, float]
    training_rows: int
    trained_window_start: Optional[datetime] = None
    trained_window_end: Optional[datetime] = None
    label_window_hours: int
    created_at: datetime
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


@router.get("/models", response_model=list[ModelVersionResponse])
async def list_models(_: User = Depends(get_current_admin_user)) -> Any:
    models = await RankingModelVersion.find_many().sort("-created_at").limit(50).to_list()
    return [
        ModelVersionResponse(
            id=str(model.id),
            name=model.name,
            is_active=bool(model.is_active),
            weights={str(k): float(v) for k, v in (model.weights or {}).items()},
            metrics={str(k): float(v) for k, v in (model.metrics or {}).items()},
            training_rows=int(model.training_rows or 0),
            trained_window_start=model.trained_window_start,
            trained_window_end=model.trained_window_end,
            label_window_hours=int(model.label_window_hours or 0),
            created_at=model.created_at,
            lifecycle=dict(model.lifecycle or {}),
            notes=model.notes,
        )
        for model in models
    ]


@router.post("/models/{model_id}/activate", response_model=ModelVersionResponse)
async def activate_model(model_id: str, _: User = Depends(get_current_admin_user)) -> Any:
    try:
        model = await ranking_model_service.activate(model_id=model_id)
    except ValueError as exc:
        if str(exc) == "model_not_found":
            raise HTTPException(status_code=404, detail="Model not found") from exc
        raise

    return ModelVersionResponse(
        id=str(model.id),
        name=model.name,
        is_active=bool(model.is_active),
        weights={str(k): float(v) for k, v in (model.weights or {}).items()},
        metrics={str(k): float(v) for k, v in (model.metrics or {}).items()},
        training_rows=int(model.training_rows or 0),
        trained_window_start=model.trained_window_start,
        trained_window_end=model.trained_window_end,
        label_window_hours=int(model.label_window_hours or 0),
        created_at=model.created_at,
        lifecycle=dict(model.lifecycle or {}),
        notes=model.notes,
    )


@router.post("/retrain", response_model=dict)
async def retrain(request: RetrainRequest, _: User = Depends(get_current_admin_user)) -> Any:
    result = await retraining_service.retrain_and_register(
        lookback_days=request.lookback_days,
        label_window_hours=request.label_window_hours,
        min_rows=request.min_rows,
        grid_step=request.grid_step,
        auto_activate=request.auto_activate,
        activation_policy=request.activation_policy,
        min_auc_gain_for_activation=request.min_auc_gain_for_activation,
        min_positive_rate_for_activation=request.min_positive_rate_for_activation,
        max_weight_shift_for_activation=request.max_weight_shift_for_activation,
        notes=request.notes,
    )
    return {
        "status": "ok",
        "window_start": result.window_start.isoformat(),
        "window_end": result.window_end.isoformat(),
        "training_rows": result.training_rows,
        "weights": result.weights,
        "metrics": result.metrics,
        "lifecycle": result.lifecycle,
        "auto_activated": bool(result.auto_activated),
        "activation_reason": result.activation_reason,
    }


@router.get("/drift", response_model=dict)
async def run_drift_check(
    lookback_days: int = settings.MLOPS_DRIFT_LOOKBACK_DAYS,
    _: User = Depends(get_current_admin_user),
) -> Any:
    report = await drift_service.run(lookback_days=lookback_days)
    return {
        "status": "ok",
        "id": str(report.id),
        "model_version_id": report.model_version_id,
        "alert": bool(report.alert),
        "alert_notified_at": report.alert_notified_at.isoformat() if report.alert_notified_at else None,
        "metrics": report.metrics,
        "created_at": report.created_at.isoformat(),
    }


@router.get("/drift/latest", response_model=dict)
async def get_latest_drift(_: User = Depends(get_current_admin_user)) -> Any:
    report = await ModelDriftReport.find_many().sort("-created_at").limit(1).to_list()
    if not report:
        return {"status": "empty"}
    item = report[0]
    return {
        "status": "ok",
        "id": str(item.id),
        "model_version_id": item.model_version_id,
        "alert": bool(item.alert),
        "alert_notified_at": item.alert_notified_at.isoformat() if item.alert_notified_at else None,
        "metrics": item.metrics,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/lifecycle", response_model=dict)
async def lifecycle_status(_: User = Depends(get_current_admin_user)) -> Any:
    latest_models = await RankingModelVersion.find_many().sort("-created_at").limit(5).to_list()
    latest_drift = await ModelDriftReport.find_many().sort("-created_at").limit(1).to_list()
    active = next((model for model in latest_models if bool(model.is_active)), None)
    if active is None:
        active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712

    model_payload = None
    if active is not None:
        model_payload = {
            "id": str(active.id),
            "name": active.name,
            "created_at": active.created_at.isoformat(),
            "weights": {str(k): float(v) for k, v in (active.weights or {}).items()},
            "metrics": {str(k): float(v) for k, v in (active.metrics or {}).items()},
            "lifecycle": dict(active.lifecycle or {}),
            "notes": active.notes,
        }

    drift_payload = None
    if latest_drift:
        drift = latest_drift[0]
        drift_payload = {
            "id": str(drift.id),
            "model_version_id": drift.model_version_id,
            "alert": bool(drift.alert),
            "alert_notified_at": drift.alert_notified_at.isoformat() if drift.alert_notified_at else None,
            "metrics": drift.metrics,
            "created_at": drift.created_at.isoformat(),
        }

    return {
        "status": "ok",
        "schedule": {
            "retrain_interval_hours": int(settings.MLOPS_RETRAIN_INTERVAL_HOURS),
            "drift_check_interval_hours": int(settings.MLOPS_DRIFT_CHECK_INTERVAL_HOURS),
            "drift_retrain_on_alert": bool(settings.MLOPS_TRIGGER_RETRAIN_ON_DRIFT_ALERT),
        },
        "activation_policy": {
            "mode": settings.MLOPS_ACTIVATION_POLICY,
            "auto_activate": bool(settings.MLOPS_AUTO_ACTIVATE),
            "min_auc_gain": float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN),
            "min_positive_rate": float(settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE),
            "max_weight_shift": float(settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT),
        },
        "alerts": {
            "enabled": bool(settings.MLOPS_ALERTS_ENABLED),
            "webhook_configured": bool((settings.MLOPS_ALERT_WEBHOOK_URL or "").strip()),
            "cooldown_minutes": int(settings.MLOPS_ALERT_COOLDOWN_MINUTES),
            "psi_alert_threshold": float(settings.MLOPS_DRIFT_PSI_ALERT_THRESHOLD),
            "z_alert_threshold": float(settings.MLOPS_DRIFT_Z_ALERT_THRESHOLD),
        },
        "active_model": model_payload,
        "latest_drift": drift_payload,
    }
