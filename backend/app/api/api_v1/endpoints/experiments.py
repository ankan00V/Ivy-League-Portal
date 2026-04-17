from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user, get_current_admin_user
from app.models.experiment import Experiment, ExperimentVariant
from app.models.user import User
from app.services.experiment_analytics_service import experiment_analytics_service
from app.services.experiment_service import experiment_service

router = APIRouter()
DEFAULT_REAL_EXPERIMENT_KEY = "ranking_mode"
DEFAULT_SIMULATED_EXPERIMENT_KEY = "ranking_mode_persona_sim"


class ExperimentVariantIn(BaseModel):
    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0.0)
    is_control: bool = False


class ExperimentCreateIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    description: Optional[str] = Field(default=None, max_length=240)
    status: str = Field(default="active")
    variants: list[ExperimentVariantIn] = Field(min_length=1)


class ExperimentUpdateIn(BaseModel):
    description: Optional[str] = Field(default=None, max_length=240)
    status: Optional[str] = None
    variants: Optional[list[ExperimentVariantIn]] = None
    rotate_salt: bool = False


@router.get("", response_model=list[dict[str, Any]])
async def list_experiments(_: User = Depends(get_current_admin_user)) -> Any:
    experiments = await Experiment.find_many().sort("-updated_at").to_list()
    return [
        {
            "key": experiment.key,
            "description": experiment.description,
            "status": experiment.status,
            "variants": [variant.model_dump() for variant in experiment.variants],
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
        description=payload.description,
        status=payload.status,  # type: ignore[arg-type]
        variants=variants,
        updated_at=datetime.utcnow(),
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

    if payload.description is not None:
        experiment.description = payload.description
    if payload.status is not None:
        experiment.status = payload.status  # type: ignore[assignment]
    if payload.variants is not None:
        variants = [ExperimentVariant(**item.model_dump()) for item in payload.variants]
        if len({v.name for v in variants}) != len(variants):
            raise HTTPException(status_code=400, detail="Variant names must be unique")
        experiment.variants = variants
    if payload.rotate_salt:
        # Rotating the salt affects only *future* users. Existing assignments remain sticky.
        from uuid import uuid4

        experiment.salt = uuid4().hex

    experiment.updated_at = datetime.utcnow()
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
