from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.models.user import User
from app.services.rag_template_registry_service import rag_template_registry_service

router = APIRouter()


class RAGTemplateCreateIn(BaseModel):
    template_key: str = Field(default="ask_ai", min_length=1)
    description: Optional[str] = None
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = Field(min_length=20)
    judge_rubric: str = Field(min_length=20)
    acceptance_thresholds: dict[str, float] = Field(default_factory=dict)
    is_online_candidate: bool = True


@router.get("/templates", response_model=list[dict])
async def list_rag_templates(
    template_key: Optional[str] = None,
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await rag_template_registry_service.list_templates(template_key=template_key)
    return [row.model_dump() for row in rows]


@router.post("/templates", response_model=dict)
async def create_rag_template(
    payload: RAGTemplateCreateIn,
    _: User = Depends(get_current_admin_user),
) -> Any:
    row = await rag_template_registry_service.create_template(
        template_key=payload.template_key,
        description=payload.description,
        retrieval_top_k=payload.retrieval_top_k,
        retrieval_settings=payload.retrieval_settings,
        system_prompt=payload.system_prompt,
        judge_rubric=payload.judge_rubric,
        acceptance_thresholds=payload.acceptance_thresholds,
        is_online_candidate=payload.is_online_candidate,
    )
    return {"status": "ok", "template_id": str(row.id), "label": row.label, "version": row.version}


@router.post("/templates/{template_id}/activate", response_model=dict)
async def activate_rag_template(
    template_id: str,
    _: User = Depends(get_current_admin_user),
) -> Any:
    try:
        row = await rag_template_registry_service.activate_template(template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "template_id": str(row.id), "label": row.label, "activated_at": datetime.utcnow()}


@router.post("/templates/{template_id}/offline-evaluate", response_model=dict)
async def offline_eval_rag_template(
    template_id: str,
    dataset_path: Optional[str] = None,
    _: User = Depends(get_current_admin_user),
) -> Any:
    try:
        run = await rag_template_registry_service.evaluate_offline(template_id=template_id, dataset_path=dataset_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return run.model_dump()


@router.post("/templates/{template_id}/online-evaluate", response_model=dict)
async def online_eval_rag_template(
    template_id: str,
    days: int = 14,
    _: User = Depends(get_current_admin_user),
) -> Any:
    try:
        run = await rag_template_registry_service.evaluate_online(template_id=template_id, days=days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return run.model_dump()


@router.get("/templates/{template_id}/evaluations", response_model=list[dict])
async def list_template_evaluations(
    template_id: str,
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await rag_template_registry_service.list_evaluations(template_id=template_id)
    return [row.model_dump() for row in rows]
