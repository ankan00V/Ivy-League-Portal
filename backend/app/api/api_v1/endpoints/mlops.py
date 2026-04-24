from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
import numpy as np
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport
from app.models.mlops_incident import MlopsIncident
from app.models.nlp_model_version import NLPModelVersion
from app.models.ranking_model_version import RankingModelVersion
from app.models.user import User
from app.services.mlops.drift_service import drift_service
from app.services.mlops.incident_service import mlops_incident_service
from app.services.mlops.retraining_service import retraining_service
from app.services.nlp_model_service import ENTITY_KEYS, nlp_model_service
from app.services.nlp_service import nlp_service
from app.services.embedding_service import embedding_service
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
    split_strategy: str = "time"
    training_metadata: dict[str, Any] = Field(default_factory=dict)
    model_card: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


class NLPExampleIn(BaseModel):
    text: str = Field(min_length=2)
    intent: str = Field(min_length=2)
    entities: dict[str, list[str]] = Field(default_factory=dict)


class NLPTrainRequest(BaseModel):
    examples: list[NLPExampleIn] = Field(min_length=20)
    ner_eval_examples: list[NLPExampleIn] = Field(default_factory=list)
    name: str = "nlp-model-v1"
    notes: Optional[str] = None
    auto_activate: bool = True
    min_intent_macro_f1_for_activation: float = Field(default=0.55, ge=0.0, le=1.0)
    min_intent_macro_f1_uplift_for_activation: float = Field(default=0.0, ge=-1.0, le=1.0)
    linear_head_learning_rate: float = Field(default=0.08, ge=0.0001, le=1.0)
    linear_head_epochs: int = Field(default=220, ge=20, le=2000)
    linear_head_l2: float = Field(default=0.0001, ge=0.0, le=1.0)


class NLPEvaluateRequest(BaseModel):
    examples: list[NLPExampleIn] = Field(min_length=5)


class NLPModelVersionResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    metrics: dict[str, float]
    training_rows: int
    intent_classifier_head: dict[str, Any] = Field(default_factory=dict)
    split_summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    baseline_confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    evaluation_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    notes: Optional[str] = None


class IncidentResponse(BaseModel):
    id: str
    incident_key: str
    source_type: str
    source_id: str
    report_id: Optional[str] = None
    model_version_id: Optional[str] = None
    severity: str
    status: str
    title: str
    summary: str
    owner: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    lessons_learned: Optional[str] = None
    review_due_at: Optional[datetime] = None
    breached_sla: bool
    resolved_at: Optional[datetime] = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class IncidentUpdateRequest(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|acknowledged|resolved)$")
    owner: Optional[str] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation: Optional[str] = None
    lessons_learned: Optional[str] = None
    action_items: Optional[list[dict[str, Any]]] = None


class IncidentTimelineAppendRequest(BaseModel):
    event: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)


def _serialize_incident(incident: MlopsIncident) -> IncidentResponse:
    return IncidentResponse(
        id=str(incident.id),
        incident_key=incident.incident_key,
        source_type=incident.source_type,
        source_id=incident.source_id,
        report_id=incident.report_id,
        model_version_id=incident.model_version_id,
        severity=incident.severity,
        status=incident.status,
        title=incident.title,
        summary=incident.summary,
        owner=incident.owner,
        root_cause=incident.root_cause,
        mitigation=incident.mitigation,
        lessons_learned=incident.lessons_learned,
        review_due_at=incident.review_due_at,
        breached_sla=bool(incident.breached_sla),
        resolved_at=incident.resolved_at,
        timeline=list(incident.timeline or []),
        action_items=list(incident.action_items or []),
        metadata=dict(incident.metadata or {}),
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _f1(precision: float, recall: float) -> float:
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _normalize_entities(payload: dict[str, list[str]]) -> dict[str, set[str]]:
    normalized: dict[str, set[str]] = {}
    for key in ENTITY_KEYS:
        values = payload.get(key) or []
        normalized[key] = {str(value).strip().lower() for value in values if str(value).strip()}
    return normalized


def _serialize_nlp_model(model: NLPModelVersion) -> NLPModelVersionResponse:
    return NLPModelVersionResponse(
        id=str(model.id),
        name=model.name,
        is_active=bool(model.is_active),
        metrics={str(k): float(v) for k, v in (model.metrics or {}).items()},
        training_rows=int(model.training_rows or 0),
        intent_classifier_head=dict(model.intent_classifier_head or {}),
        split_summary=dict(model.split_summary or {}),
        metadata=dict(model.metadata or {}),
        confusion_matrix={str(k): {str(pk): int(pv) for pk, pv in (row or {}).items()} for k, row in (model.confusion_matrix or {}).items()},
        baseline_confusion_matrix={
            str(k): {str(pk): int(pv) for pk, pv in (row or {}).items()}
            for k, row in (model.baseline_confusion_matrix or {}).items()
        },
        evaluation_snapshot=dict(model.evaluation_snapshot or {}),
        created_at=model.created_at,
        updated_at=model.updated_at,
        notes=model.notes,
    )


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
            split_strategy=model.split_strategy,
            training_metadata=dict(model.training_metadata or {}),
            model_card=dict(model.model_card or {}),
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
        split_strategy=model.split_strategy,
        training_metadata=dict(model.training_metadata or {}),
        model_card=dict(model.model_card or {}),
        notes=model.notes,
    )


@router.get("/nlp/models", response_model=list[NLPModelVersionResponse])
async def list_nlp_models(_: User = Depends(get_current_admin_user)) -> Any:
    models = await NLPModelVersion.find_many().sort("-created_at").limit(50).to_list()
    return [_serialize_nlp_model(model) for model in models]


@router.post("/nlp/models/{model_id}/activate", response_model=NLPModelVersionResponse)
async def activate_nlp_model(model_id: str, _: User = Depends(get_current_admin_user)) -> Any:
    try:
        model = await nlp_model_service.activate(model_id=model_id)
    except ValueError as exc:
        if str(exc) == "model_not_found":
            raise HTTPException(status_code=404, detail="NLP model not found") from exc
        raise
    return _serialize_nlp_model(model)


@router.post("/nlp/train", response_model=dict)
async def train_nlp_model(request: NLPTrainRequest, _: User = Depends(get_current_admin_user)) -> Any:
    model = await nlp_model_service.train_and_register(
        examples=[example.model_dump() for example in request.examples],
        name=request.name,
        notes=request.notes,
        auto_activate=request.auto_activate,
        min_intent_macro_f1_for_activation=request.min_intent_macro_f1_for_activation,
        min_intent_macro_f1_uplift_for_activation=request.min_intent_macro_f1_uplift_for_activation,
        ner_eval_examples=[example.model_dump() for example in request.ner_eval_examples] if request.ner_eval_examples else None,
        linear_head_learning_rate=request.linear_head_learning_rate,
        linear_head_epochs=request.linear_head_epochs,
        linear_head_l2=request.linear_head_l2,
    )
    return {
        "status": "ok",
        "model": _serialize_nlp_model(model).model_dump(),
    }


@router.post("/nlp/evaluate", response_model=dict)
async def evaluate_nlp_model(request: NLPEvaluateRequest, _: User = Depends(get_current_admin_user)) -> Any:
    examples = request.examples
    labels = sorted({example.intent.strip().lower() for example in examples if example.intent.strip()})
    if not labels:
        raise HTTPException(status_code=400, detail="No valid intent labels in examples")

    confusion: dict[str, dict[str, int]] = {label: {pred: 0 for pred in labels} for label in labels}
    baseline_confusion: dict[str, dict[str, int]] = {label: {pred: 0 for pred in labels} for label in labels}
    correct = 0
    baseline_correct = 0
    entity_tp = 0
    entity_fp = 0
    entity_fn = 0

    active_model = await nlp_model_service.get_active()
    centroids = {
        label: np.asarray(vector, dtype=np.float32)
        for label, vector in (active_model.intent_centroids or {}).items()
        if np.asarray(vector).size > 0
    }

    for row in examples:
        expected_intent = row.intent.strip().lower()
        query_embedding = await embedding_service.embed_query(row.text)
        if centroids:
            best_label = labels[0] if labels else "internships"
            best_score = -2.0
            for label, centroid in centroids.items():
                if centroid.shape != query_embedding.shape:
                    continue
                score = float(np.dot(query_embedding, centroid))
                if score > best_score:
                    best_score = score
                    best_label = label
            baseline_intent = best_label
        else:
            baseline_intent = "internships"

        prediction = await nlp_service.classify_intent(row.text)
        predicted_intent = str(prediction.get("intent") or "").strip().lower() or "internships"
        if expected_intent not in confusion:
            confusion[expected_intent] = {}
        if expected_intent not in baseline_confusion:
            baseline_confusion[expected_intent] = {}
        confusion[expected_intent][predicted_intent] = confusion[expected_intent].get(predicted_intent, 0) + 1
        baseline_confusion[expected_intent][baseline_intent] = baseline_confusion[expected_intent].get(baseline_intent, 0) + 1
        if predicted_intent == expected_intent:
            correct += 1
        if baseline_intent == expected_intent:
            baseline_correct += 1

        predicted_entities = await nlp_service.extract_entities_with_model(row.text)
        expected_entities = _normalize_entities(row.entities)
        actual_entities = _normalize_entities(predicted_entities)
        for key in ENTITY_KEYS:
            pred_set = actual_entities.get(key, set())
            true_set = expected_entities.get(key, set())
            entity_tp += len(pred_set.intersection(true_set))
            entity_fp += len(pred_set - true_set)
            entity_fn += len(true_set - pred_set)

    intent_accuracy = float(correct / max(1, len(examples)))
    baseline_accuracy = float(baseline_correct / max(1, len(examples)))
    per_label_f1: list[float] = []
    baseline_per_label_f1: list[float] = []
    for label in labels:
        tp = int(confusion.get(label, {}).get(label, 0))
        fp = sum(int(confusion.get(other, {}).get(label, 0)) for other in labels if other != label)
        fn = sum(int(confusion.get(label, {}).get(other, 0)) for other in labels if other != label)
        precision = float(tp / max(1, tp + fp))
        recall = float(tp / max(1, tp + fn))
        per_label_f1.append(_f1(precision, recall))
        b_tp = int(baseline_confusion.get(label, {}).get(label, 0))
        b_fp = sum(int(baseline_confusion.get(other, {}).get(label, 0)) for other in labels if other != label)
        b_fn = sum(int(baseline_confusion.get(label, {}).get(other, 0)) for other in labels if other != label)
        b_precision = float(b_tp / max(1, b_tp + b_fp))
        b_recall = float(b_tp / max(1, b_tp + b_fn))
        baseline_per_label_f1.append(_f1(b_precision, b_recall))
    intent_macro_f1 = float(sum(per_label_f1) / max(1, len(per_label_f1)))
    baseline_intent_macro_f1 = float(sum(baseline_per_label_f1) / max(1, len(baseline_per_label_f1)))

    entity_precision = float(entity_tp / max(1, entity_tp + entity_fp))
    entity_recall = float(entity_tp / max(1, entity_tp + entity_fn))
    entity_micro_f1 = _f1(entity_precision, entity_recall)

    return {
        "status": "ok",
        "rows": len(examples),
        "intent_metrics": {
            "accuracy": round(intent_accuracy, 6),
            "macro_f1": round(intent_macro_f1, 6),
            "baseline_accuracy": round(baseline_accuracy, 6),
            "baseline_macro_f1": round(baseline_intent_macro_f1, 6),
            "macro_f1_uplift_vs_baseline": round(intent_macro_f1 - baseline_intent_macro_f1, 6),
            "confusion_matrix": confusion,
            "baseline_confusion_matrix": baseline_confusion,
        },
        "entity_metrics": {
            "precision": round(entity_precision, 6),
            "recall": round(entity_recall, 6),
            "micro_f1": round(entity_micro_f1, 6),
        },
    }


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
        "split_strategy": result.split_strategy,
        "training_metadata": result.training_metadata,
        "model_card": result.model_card,
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
            "guardrail_lookback_days": int(settings.MLOPS_GUARDRAIL_LOOKBACK_DAYS),
            "guardrail_require_online_kpis": bool(settings.MLOPS_GUARDRAIL_REQUIRE_ONLINE_KPIS),
            "max_apply_rate_drop": float(settings.MLOPS_GUARDRAIL_MAX_APPLY_RATE_DROP),
            "max_freshness_regression_seconds": float(settings.MLOPS_GUARDRAIL_MAX_FRESHNESS_REGRESSION_SECONDS),
            "max_latency_p95_regression_ms": float(settings.MLOPS_GUARDRAIL_MAX_LATENCY_P95_REGRESSION_MS),
            "max_failure_rate_regression": float(settings.MLOPS_GUARDRAIL_MAX_FAILURE_RATE_REGRESSION),
            "parity_enabled": bool(settings.MLOPS_PARITY_ENABLED),
            "parity_min_real_impressions_per_mode": int(settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE),
            "parity_min_real_requests_per_mode": int(settings.MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE),
            "parity_max_ctr_regression": float(settings.MLOPS_PARITY_MAX_CTR_REGRESSION),
            "parity_max_apply_rate_regression": float(settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION),
            "parity_min_offline_auc_gain_for_online_gates": float(
                settings.MLOPS_PARITY_MIN_OFFLINE_AUC_GAIN_FOR_ONLINE_GATES
            ),
        },
        "alerts": {
            "enabled": bool(settings.MLOPS_ALERTS_ENABLED),
            "webhook_configured": bool((settings.MLOPS_ALERT_WEBHOOK_URL or "").strip()),
            "slack_configured": bool((settings.MLOPS_ALERT_SLACK_WEBHOOK_URL or "").strip()),
            "pagerduty_configured": bool((settings.MLOPS_ALERT_PAGERDUTY_ROUTING_KEY or "").strip()),
            "cooldown_minutes": int(settings.MLOPS_ALERT_COOLDOWN_MINUTES),
            "psi_alert_threshold": float(settings.MLOPS_DRIFT_PSI_ALERT_THRESHOLD),
            "z_alert_threshold": float(settings.MLOPS_DRIFT_Z_ALERT_THRESHOLD),
            "incident_auto_create": bool(settings.MLOPS_INCIDENT_AUTO_CREATE),
            "incident_review_due_hours": int(settings.MLOPS_INCIDENT_REVIEW_DUE_HOURS),
            "incident_breach_sla_hours": int(settings.MLOPS_INCIDENT_BREACH_SLA_HOURS),
        },
        "active_model": model_payload,
        "latest_drift": drift_payload,
    }


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    breached_sla: Optional[bool] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: User = Depends(get_current_admin_user),
) -> Any:
    filters: list[Any] = []
    if status:
        filters.append(MlopsIncident.status == status.strip().lower())
    if severity:
        filters.append(MlopsIncident.severity == severity.strip().lower())
    if breached_sla is not None:
        filters.append(MlopsIncident.breached_sla == bool(breached_sla))
    rows = await MlopsIncident.find_many(*filters).sort("-created_at").limit(int(limit)).to_list()
    output: list[IncidentResponse] = []
    for row in rows:
        refreshed = await mlops_incident_service.refresh_sla(row)
        output.append(_serialize_incident(refreshed))
    return output


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str, _: User = Depends(get_current_admin_user)) -> Any:
    incident = await MlopsIncident.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident = await mlops_incident_service.refresh_sla(incident)
    return _serialize_incident(incident)


@router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: str,
    request: IncidentUpdateRequest,
    _: User = Depends(get_current_admin_user),
) -> Any:
    incident = await MlopsIncident.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    if request.status is not None:
        incident.status = request.status.strip().lower()
        if incident.status == "resolved":
            incident.resolved_at = datetime.utcnow()
    if request.owner is not None:
        incident.owner = request.owner.strip() or None
    if request.summary is not None:
        incident.summary = request.summary.strip()
    if request.root_cause is not None:
        incident.root_cause = request.root_cause.strip() or None
    if request.mitigation is not None:
        incident.mitigation = request.mitigation.strip() or None
    if request.lessons_learned is not None:
        incident.lessons_learned = request.lessons_learned.strip() or None
    if request.action_items is not None:
        incident.action_items = list(request.action_items)

    incident.updated_at = datetime.utcnow()
    await incident.save()
    incident = await mlops_incident_service.refresh_sla(incident)
    return _serialize_incident(incident)


@router.post("/incidents/{incident_id}/timeline", response_model=IncidentResponse)
async def append_incident_timeline(
    incident_id: str,
    request: IncidentTimelineAppendRequest,
    _: User = Depends(get_current_admin_user),
) -> Any:
    incident = await MlopsIncident.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident = await mlops_incident_service.append_timeline(
        incident=incident,
        event=request.event,
        message=request.message,
        payload=request.payload,
    )
    incident = await mlops_incident_service.refresh_sla(incident)
    return _serialize_incident(incident)
