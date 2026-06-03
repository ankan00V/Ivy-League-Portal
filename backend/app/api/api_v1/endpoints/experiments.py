from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user, get_current_admin_user
from app.models.experiment import Experiment, ExperimentStatus, ExperimentVariant, PrimaryMetric, RankingMode
from app.models.user import User
from app.services.experiment_analytics_service import experiment_analytics_service
from app.services.experiment_service import experiment_service
from app.core.time import utc_now
from app.services.auth_security_service import auth_security_service

router = APIRouter()
DEFAULT_REAL_EXPERIMENT_KEY = "ranking_mode"
DEFAULT_SIMULATED_EXPERIMENT_KEY = "ranking_mode_persona_sim"


class ExperimentVariantIn(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0.0)
    traffic_fraction: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ranking_mode: Optional[RankingMode] = None
    description: Optional[str] = Field(default=None, max_length=240)
    exclude_cold_start: bool = False
    is_control: bool = False


class ExperimentCreateIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=240)
    status: ExperimentStatus = "draft"
    variants: list[ExperimentVariantIn] = Field(min_length=1)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_sample_size: int = Field(default=200, ge=1)
    primary_metric: PrimaryMetric = "ctr"
    guardrail_metrics: list[str] = Field(default_factory=lambda: ["apply_rate", "save_rate"])


class ExperimentUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=240)
    status: Optional[ExperimentStatus] = None
    variants: Optional[list[ExperimentVariantIn]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_sample_size: Optional[int] = Field(default=None, ge=1)
    primary_metric: Optional[PrimaryMetric] = None
    guardrail_metrics: Optional[list[str]] = None
    rotate_salt: bool = False


@router.get("", response_model=list[dict[str, Any]])
async def list_experiments(_: User = Depends(get_current_admin_user)) -> Any:
    experiments = await Experiment.find_many().sort("-updated_at").to_list()
    return [
        {
            "key": experiment.key,
            "name": experiment.name,
            "description": experiment.description,
            "status": experiment.status,
            "variants": [variant.model_dump() for variant in experiment.variants],
            "start_date": experiment.start_date,
            "end_date": experiment.end_date,
            "min_sample_size": experiment.min_sample_size,
            "primary_metric": experiment.primary_metric,
            "guardrail_metrics": experiment.guardrail_metrics,
            "default_variant": experiment.default_variant,
            "winning_variant": experiment.winning_variant,
            "graduated_at": experiment.graduated_at,
            "updated_at": experiment.updated_at,
            "created_at": experiment.created_at,
        }
        for experiment in experiments
    ]


@router.post("", response_model=dict)
async def create_experiment(payload: ExperimentCreateIn, _: User = Depends(get_current_admin_user)) -> Any:
    existing = await Experiment.find_one(Experiment.key == payload.key)
    if existing:
        raise HTTPException(status_code=400, detail="Experiment key already exists")

    variants = [ExperimentVariant(**item.model_dump()) for item in payload.variants]
    if len({v.name for v in variants}) != len(variants):
        raise HTTPException(status_code=400, detail="Variant names must be unique")

    experiment = Experiment(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        status=payload.status,  # type: ignore[arg-type]
        variants=variants,
        start_date=payload.start_date,
        end_date=payload.end_date,
        min_sample_size=payload.min_sample_size,
        primary_metric=payload.primary_metric,
        guardrail_metrics=payload.guardrail_metrics,
        updated_at=utc_now(),
    )
    await experiment.insert()
    return {"status": "ok", "key": experiment.key}


@router.patch("/{experiment_key}", response_model=dict)
async def update_experiment(
    experiment_key: str,
    payload: ExperimentUpdateIn,
    _: User = Depends(get_current_admin_user),
) -> Any:
    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if payload.name is not None:
        experiment.name = payload.name
    if payload.description is not None:
        experiment.description = payload.description
    if payload.status is not None:
        experiment.status = payload.status  # type: ignore[assignment]
    if payload.variants is not None:
        variants = [ExperimentVariant(**item.model_dump()) for item in payload.variants]
        if len({v.name for v in variants}) != len(variants):
            raise HTTPException(status_code=400, detail="Variant names must be unique")
        experiment.variants = variants
    if payload.start_date is not None:
        experiment.start_date = payload.start_date
    if payload.end_date is not None:
        experiment.end_date = payload.end_date
    if payload.min_sample_size is not None:
        experiment.min_sample_size = payload.min_sample_size
    if payload.primary_metric is not None:
        experiment.primary_metric = payload.primary_metric
    if payload.guardrail_metrics is not None:
        experiment.guardrail_metrics = payload.guardrail_metrics
    if payload.rotate_salt:
        # Rotating the salt affects only *future* users. Existing assignments remain sticky.
        from uuid import uuid4

        experiment.salt = uuid4().hex

    experiment.updated_at = utc_now()
    await experiment.save()
    return {"status": "ok"}


@router.get("/{experiment_key}/my-assignment", response_model=dict)
async def my_assignment(
    experiment_key: str,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    decision = await experiment_service.assign(user_id=current_user.id, experiment_key=experiment_key)
    if not decision:
        raise HTTPException(status_code=404, detail="Experiment not found or inactive")
    return {
        "experiment_key": decision.experiment_key,
        "variant": decision.variant,
        "is_control": decision.is_control,
        "bucket": decision.bucket,
        "assigned_at": decision.assigned_at,
    }


@router.get("/{experiment_key}/report", response_model=dict)
async def experiment_report(
    experiment_key: str,
    days: int = 30,
    conversion: str = "click",
    traffic_type: Literal["all", "real", "simulated"] = "all",
    _: User = Depends(get_current_admin_user),
) -> Any:
    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    conversion_types = [value.strip() for value in conversion.split(",") if value.strip()]
    return await experiment_analytics_service.report(
        experiment=experiment,
        days=days,
        conversion_types=conversion_types,
        traffic_type=traffic_type,
    )


@router.get("/{experiment_key}/results", response_model=dict)
async def experiment_results(
    experiment_key: str,
    days: int = 30,
    traffic_type: Literal["all", "real", "simulated"] = "all",
    _: User = Depends(get_current_admin_user),
) -> Any:
    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return await experiment_analytics_service.results(
        experiment=experiment,
        days=days,
        traffic_type=traffic_type,
    )


async def _audit_experiment_action(
    *,
    action: str,
    actor: User,
    experiment_key: str,
    success: bool,
    reason: str,
    request: Request | None,
) -> None:
    ip_address = str(request.client.host) if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None
    await auth_security_service.audit_event(
        event_type=f"experiment.{action}",
        email=str(getattr(actor, "email", "") or "").strip().lower() or None,
        account_type=str(getattr(actor, "account_type", "candidate") or "candidate"),
        purpose="admin",
        success=success,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
        user_id=actor.id,
    )


@router.post("/{experiment_key}/graduation/check", response_model=dict)
async def check_experiment_graduation(
    experiment_key: str,
    days: int = 30,
    traffic_type: Literal["real", "all", "simulated"] = "real",
    force: bool = False,
    request: Request = None,  # type: ignore[assignment]
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    experiment = await Experiment.find_one(Experiment.key == experiment_key)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    result = await experiment_analytics_service.maybe_graduate(
        experiment=experiment,
        days=days,
        traffic_type=traffic_type,
        force=force,
    )
    await _audit_experiment_action(
        action="graduation_check",
        actor=current_user,
        experiment_key=experiment_key,
        success=bool(result.get("graduated")),
        reason=str({"experiment_key": experiment_key, "result": result.get("reason"), "force": force}),
        request=request,
    )
    return result


@router.post("/graduation/run", response_model=dict)
async def run_experiment_graduation(
    days: int = 30,
    traffic_type: Literal["real", "all", "simulated"] = "real",
    request: Request = None,  # type: ignore[assignment]
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    experiments = await Experiment.find_many().to_list()
    eligible = [item for item in experiments if item.status in {"active", "running"}]
    results: list[dict[str, Any]] = []
    for experiment in eligible:
        results.append(
            await experiment_analytics_service.maybe_graduate(
                experiment=experiment,
                days=days,
                traffic_type=traffic_type,
            )
        )
    graduated = [item for item in results if item.get("graduated")]
    await _audit_experiment_action(
        action="graduation_run",
        actor=current_user,
        experiment_key="*",
        success=True,
        reason=str({"checked": len(eligible), "graduated": len(graduated)}),
        request=request,
    )
    return {
        "checked": len(eligible),
        "graduated": len(graduated),
        "results": results,
    }


@router.get("/reports", response_model=list[dict])
async def all_experiment_reports(
    days: int = 30,
    conversion: str = "click",
    traffic_type: Literal["all", "real", "simulated"] = "all",
    _: User = Depends(get_current_admin_user),
) -> Any:
    conversion_types = [value.strip() for value in conversion.split(",") if value.strip()]
    experiments = await Experiment.find_many(Experiment.status != "archived").to_list()
    reports: list[dict[str, Any]] = []
    for experiment in experiments:
        reports.append(
            await experiment_analytics_service.report(
                experiment=experiment,
                days=days,
                conversion_types=conversion_types,
                traffic_type=traffic_type,
            )
        )
    return reports


@router.get("/reports/side-by-side", response_model=dict)
async def side_by_side_reports(
    days: int = 30,
    conversion: str = "click,apply,save",
    real_experiment_key: str = DEFAULT_REAL_EXPERIMENT_KEY,
    simulated_experiment_key: str = DEFAULT_SIMULATED_EXPERIMENT_KEY,
    _: User = Depends(get_current_admin_user),
) -> Any:
    conversion_types = [value.strip() for value in conversion.split(",") if value.strip()]
    if not conversion_types:
        conversion_types = ["click", "apply", "save"]
    ordered_conversion_types = list(dict.fromkeys(conversion_types))

    async def _build_bundle(experiment_key: str, label: str) -> dict[str, Any]:
        experiment = await Experiment.find_one(Experiment.key == experiment_key)
        if not experiment:
            return {
                "label": label,
                "experiment_key": experiment_key,
                "status": "missing",
                "reports": {},
            }

        reports_by_conversion: dict[str, Any] = {}
        for conversion_type in ordered_conversion_types:
            reports_by_conversion[conversion_type] = await experiment_analytics_service.report(
                experiment=experiment,
                days=days,
                conversion_types=[conversion_type],
                traffic_type="real" if label == "real" else "simulated",
            )

        return {
            "label": label,
            "experiment_key": experiment_key,
            "status": "ok",
            "reports": reports_by_conversion,
        }

    real_bundle = await _build_bundle(real_experiment_key, "real")
    simulated_bundle = await _build_bundle(simulated_experiment_key, "simulated")

    return {
        "days": max(1, min(int(days), 365)),
        "conversion_types": ordered_conversion_types,
        "real": real_bundle,
        "simulated": simulated_bundle,
    }
