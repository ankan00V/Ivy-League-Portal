from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from beanie import PydanticObjectId
from beanie.odm.operators.find.comparison import In
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.core.time import utc_now
from app.models.source_discovery import (
    BadDomainEntry,
    CompanySeed,
    DiscoveredSource,
    DiscoveryLLMCall,
    DiscoveryMethod,
    SourceDiscoveryRun,
    SourceStatus,
)
from app.models.user import User
from app.services.job_runner import job_runner
from app.services.source_discovery import (
    QUEUE_SOURCE_EXTRACTION,
    QUEUE_SOURCE_QUALIFICATION,
    RedisQueue,
    adaptive_extraction_service,
    probation_manager,
    source_discovery_engine,
    source_qualification_service,
    trust_scoring_engine,
)

router = APIRouter()
seed_router = APIRouter()
review_router = APIRouter()


class ManualReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class OverrideTrustRequest(BaseModel):
    trust_score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=1000)
    approve: bool = True


class BadDomainRequest(BaseModel):
    domain: str = Field(min_length=3)
    reason: str = Field(min_length=3, max_length=300)


class SeedCreateRequest(BaseModel):
    company_name: str
    domain: str
    careers_url: Optional[str] = None
    industry: str = "technology"
    company_size: str = "mid"
    india_presence: bool = True
    student_friendly: bool = True
    priority_tier: Optional[str] = None
    source_category: Optional[str] = None
    check_cadence_hours: int = Field(default=168, ge=1, le=2160)
    target_roles: list[str] = Field(default_factory=lambda: ["internship", "0-1 years", "early career"])
    notes: Optional[str] = None


def _json_doc(row: Any) -> dict[str, Any]:
    payload = row.model_dump(mode="json")
    payload["id"] = str(row.id)
    return payload


def _source_progress(row: DiscoveredSource) -> str:
    if row.status != SourceStatus.probation:
        return str(row.status)
    rates = list(row.probation_parse_rates or [])
    avg = sum(rates) / max(1, len(rates))
    return f"{int(row.probation_runs or 0)}/{int(getattr(settings, 'PROBATION_MIN_RUNS', 3))} runs complete, avg parse rate {avg:.0%}"


@router.get("/overview", response_model=dict)
async def discovery_overview(_: User = Depends(get_current_admin_user)) -> Any:
    since_30 = utc_now() - timedelta(days=30)
    since_7 = utc_now() - timedelta(days=7)
    rows = await DiscoveredSource.find_many().to_list()
    recent = [row for row in rows if row.discovered_at >= since_30]
    rejection_reasons: dict[str, int] = {}
    extraction_methods: dict[str, int] = {}
    for row in rows:
        if row.rejection_reason:
            key = str(row.rejection_reason).split(":", 1)[0]
            rejection_reasons[key] = rejection_reasons.get(key, 0) + 1
        method = str((row.parser_template or {}).get("extraction_method") or "")
        if method:
            extraction_methods[method] = extraction_methods.get(method, 0) + 1
    llm_rows = await DiscoveryLLMCall.find_many(DiscoveryLLMCall.created_at >= since_30).to_list()
    return {
        "pipeline_funnel": {
            "discovered_last_30_days": len(recent),
            "qualified": sum(1 for row in rows if row.status == SourceStatus.qualified),
            "extracted": sum(1 for row in rows if row.extracted_at is not None),
            "in_probation": sum(1 for row in rows if row.status == SourceStatus.probation),
            "promoted": sum(1 for row in rows if row.status == SourceStatus.promoted),
            "rejected": sum(1 for row in rows if row.status == SourceStatus.rejected),
            "quarantined": sum(1 for row in rows if row.status == SourceStatus.quarantined),
        },
        "qualification_rejection_reasons": rejection_reasons,
        "extraction_methods": extraction_methods,
        "llm_extraction_cost_usd_last_30_days": round(sum(float(row.cost_estimate_usd or 0) for row in llm_rows), 4),
        "new_sources_promoted_this_week": sum(1 for row in rows if row.promoted_at and row.promoted_at >= since_7),
        "sources_quarantined_this_week": sum(1 for row in rows if row.status == SourceStatus.quarantined and row.updated_at >= since_7),
        "generated_at": utc_now(),
    }


@router.get("/sources", response_model=dict)
async def discovery_sources(
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_admin_user),
) -> Any:
    skip = (page - 1) * limit
    filters = []
    if status:
        try:
            parsed_status = SourceStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status")
        filters.append(DiscoveredSource.status == parsed_status)
    rows = await DiscoveredSource.find_many(*filters).sort("-discovered_at").skip(skip).limit(limit).to_list()
    total = await DiscoveredSource.find_many(*filters).count()
    items = []
    for row in rows:
        payload = _json_doc(row)
        payload["sample_opportunities"] = (row.sample_opportunities or [])[:1]
        payload["probation_progress"] = _source_progress(row)
        items.append(payload)
    return {"items": items, "page": page, "limit": limit, "total": total}


@router.get("/sources/{source_id}", response_model=dict)
async def discovery_source_detail(
    source_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    row = await DiscoveredSource.get(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _json_doc(row)


@router.get("/runs", response_model=list[dict[str, Any]])
async def discovery_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await SourceDiscoveryRun.find_many().sort("-started_at").limit(limit).to_list()
    return [_json_doc(row) for row in rows]


@router.post("/run", response_model=dict)
async def trigger_discovery_run(
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    job = await job_runner.enqueue(
        job_type="source_discovery_run",
        payload={"triggered_by": f"admin:{str(current_user.id)}"},
        max_attempts=1,
        dedupe_key=f"source_discovery_run:manual:{utc_now().strftime('%Y%m%d%H')}",
    )
    return {"status": "queued", "job_id": str(job.id)}


@router.get("/sources/{source_id}/trust-analysis", response_model=dict)
async def trust_analysis(
    source_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.trust_score is None:
        source = await trust_scoring_engine.score_source(source.id)
    rates = list(source.probation_parse_rates or [])
    avg = sum(rates) / max(1, len(rates))
    recommendation = "Needs more runs"
    if source.status == SourceStatus.promoted:
        recommendation = "Promoted"
    elif source.trust_score and source.trust_score >= float(getattr(settings, "TRUST_MIN_SCORE_AUTO_PROMOTE", 70)) and avg >= float(getattr(settings, "PROBATION_MIN_PARSE_RATE", 0.70)):
        recommendation = "Promote"
    elif source.requires_admin_review:
        recommendation = "Requires review"
    elif source.status == SourceStatus.rejected:
        recommendation = "Reject"
    return {
        "source": _json_doc(source),
        "trust_breakdown": source.trust_breakdown or {},
        "sample_opportunities": source.sample_opportunities or [],
        "probation_run_history": {
            "runs": source.probation_runs,
            "items_fetched": source.probation_items_fetched,
            "parse_rates": source.probation_parse_rates,
            "failures": source.probation_failures,
        },
        "recommendation": recommendation,
    }


@router.get("/sources/{source_id}/trust-reasoning", response_model=dict)
async def trust_reasoning(
    source_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.trust_score is None:
        source = await trust_scoring_engine.score_source(source.id)
    parts = [f"{source.name or source.domain} scored {source.trust_score or 0:.0f}/100:"]
    for key, value in (source.trust_breakdown or {}).items():
        parts.append(f"- {key.replace('_', ' ').title()}: {value.get('score')}/{value.get('max')} ({value.get('details')})")
    if source.probation_runs:
        avg = sum(source.probation_parse_rates or []) / max(1, len(source.probation_parse_rates or []))
        parts.append(f"Probation: {source.probation_runs} runs, avg parse rate {avg:.0%}.")
    return {"reasoning": "\n".join(parts)}


@router.post("/sources/{source_id}/force-qualify", response_model=dict)
async def force_qualify(
    source_id: PydanticObjectId,
    payload: ManualReasonRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.status = SourceStatus.qualified
    source.qualified_at = utc_now()
    source.admin_notes = f"{source.admin_notes or ''}\nforce_qualify:{payload.reason}".strip()
    source.admin_reviewed_by = str(current_user.id)
    source.admin_reviewed_at = utc_now()
    await source.save()
    await RedisQueue().push(QUEUE_SOURCE_EXTRACTION, str(source.id))
    return {"status": "qualified", "source": _json_doc(source)}


@router.post("/sources/{source_id}/force-promote", response_model=dict)
async def force_promote(
    source_id: PydanticObjectId,
    payload: ManualReasonRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.admin_notes = f"{source.admin_notes or ''}\nforce_promote:{payload.reason}".strip()
    source.requires_admin_review = False
    source.admin_hold = False
    await source.save()
    promoted = await trust_scoring_engine.promote_source(source.id, promoted_by=str(current_user.id))
    return {"status": "promoted", "source": _json_doc(promoted)}


@router.post("/sources/{source_id}/reject", response_model=dict)
async def reject_source(
    source_id: PydanticObjectId,
    payload: ManualReasonRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await trust_scoring_engine.reject_source(source_id, reason=payload.reason, actor=str(current_user.id))
    return {"status": "rejected", "source": _json_doc(source)}


@router.post("/sources/{source_id}/trigger-extraction", response_model=dict)
async def trigger_extraction(
    source_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    source = await adaptive_extraction_service.extract_source(source_id)
    return {"status": source.status, "source": _json_doc(source)}


@router.post("/sources/{source_id}/trigger-probation-run", response_model=dict)
async def trigger_probation_run(
    source_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    source = await probation_manager.run_probation_scrape(source_id)
    return {"status": source.status, "source": _json_doc(source)}


@router.post("/sources/{source_id}/override-trust", response_model=dict)
async def override_trust(
    source_id: PydanticObjectId,
    payload: OverrideTrustRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.trust_score = payload.trust_score
    source.trust_breakdown = source.trust_breakdown or {}
    source.trust_breakdown["admin_override"] = {
        "score": payload.trust_score,
        "max": 100,
        "details": payload.reason,
        "actor": str(current_user.id),
    }
    source.admin_reviewed_by = str(current_user.id)
    source.admin_reviewed_at = utc_now()
    source.requires_admin_review = False
    await source.save()
    if payload.approve:
        source = await trust_scoring_engine.promote_source(source.id, promoted_by=str(current_user.id))
    return {"status": source.status, "source": _json_doc(source)}


@router.get("/bad-domains", response_model=dict)
async def bad_domains(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
) -> Any:
    skip = (page - 1) * limit
    rows = await BadDomainEntry.find_many().sort("-added_at").skip(skip).limit(limit).to_list()
    total = await BadDomainEntry.find_many().count()
    return {"items": [_json_doc(row) for row in rows], "total": total, "page": page, "limit": limit}


@router.post("/bad-domains", response_model=dict)
async def add_bad_domain(
    payload: BadDomainRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    existing = await BadDomainEntry.find_one(BadDomainEntry.domain == payload.domain)
    if existing:
        existing.reason = payload.reason
        existing.added_by = str(current_user.id)
        existing.added_at = utc_now()
        await existing.save()
        return _json_doc(existing)
    row = BadDomainEntry(domain=payload.domain, reason=payload.reason, added_by=str(current_user.id))
    await row.insert()
    return _json_doc(row)


@router.delete("/bad-domains/{domain}", response_model=dict)
async def delete_bad_domain(
    domain: str,
    _: User = Depends(get_current_admin_user),
) -> Any:
    row = await BadDomainEntry.find_one(BadDomainEntry.domain == domain)
    if row is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    await row.delete()
    return {"status": "deleted", "domain": domain}


@router.get("/llm-costs", response_model=dict)
async def llm_costs(_: User = Depends(get_current_admin_user)) -> Any:
    now = utc_now()
    rows = await DiscoveryLLMCall.find_many(DiscoveryLLMCall.created_at >= now - timedelta(days=31)).to_list()

    def summarize(since: Any) -> dict[str, Any]:
        scoped = [row for row in rows if row.created_at >= since]
        return {
            "calls": len(scoped),
            "tokens": sum(int(row.tokens_used or 0) for row in scoped),
            "cost_usd": round(sum(float(row.cost_estimate_usd or 0) for row in scoped), 4),
        }

    month = summarize(now - timedelta(days=31))
    budget = float(getattr(settings, "MONTHLY_LLM_BUDGET_USD", 20.0))
    elapsed_days = max(1, now.day)
    projected = month["cost_usd"] / elapsed_days * 31
    return {
        "today": summarize(now - timedelta(days=1)),
        "this_week": summarize(now - timedelta(days=7)),
        "this_month": month,
        "budget_remaining_usd": round(max(0.0, budget - month["cost_usd"]), 4),
        "projected_month_end": round(projected, 4),
    }


@router.post("/bulk-import", response_model=dict)
async def bulk_import_sources(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    raw = await file.read()
    return await source_discovery_engine.bulk_import_sources(
        csv_text=raw.decode("utf-8-sig"),
        actor=current_user,
    )


@review_router.post("/review-queue", response_model=list[dict[str, Any]])
@review_router.get("/review-queue", response_model=list[dict[str, Any]])
async def source_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await DiscoveredSource.find_many(
        DiscoveredSource.requires_admin_review == True,  # noqa: E712
        In(DiscoveredSource.status, [SourceStatus.probation, SourceStatus.qualified, SourceStatus.rejected]),
    ).sort("-updated_at").limit(limit).to_list()
    return [_json_doc(row) for row in rows]


@review_router.post("/{source_id}/approve", response_model=dict)
async def approve_review_source(
    source_id: PydanticObjectId,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await DiscoveredSource.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.requires_admin_review = False
    source.admin_reviewed_by = str(current_user.id)
    source.admin_reviewed_at = utc_now()
    await source.save()
    promoted = await trust_scoring_engine.promote_source(source.id, promoted_by=str(current_user.id))
    return {"status": "approved", "source": _json_doc(promoted)}


@review_router.post("/{source_id}/reject", response_model=dict)
async def reject_review_source(
    source_id: PydanticObjectId,
    payload: ManualReasonRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    source = await trust_scoring_engine.reject_source(source_id, reason=payload.reason, actor=str(current_user.id))
    return {"status": "rejected", "source": _json_doc(source)}


@review_router.post("/{source_id}/override-trust", response_model=dict)
async def review_override_trust(
    source_id: PydanticObjectId,
    payload: OverrideTrustRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    return await override_trust(source_id=source_id, payload=payload, current_user=current_user)


@seed_router.get("", response_model=dict)
async def list_seeds(
    limit: int = Query(default=100, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await CompanySeed.find_many().sort("company_name").skip(skip).limit(limit).to_list()
    total = await CompanySeed.find_many().count()
    return {"items": [_json_doc(row) for row in rows], "total": total, "limit": limit, "skip": skip}


@seed_router.post("", response_model=dict)
async def add_seed(
    payload: SeedCreateRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    existing = await CompanySeed.find_one(CompanySeed.domain == payload.domain)
    if existing:
        raise HTTPException(status_code=409, detail="Seed domain already exists")
    row = CompanySeed(**payload.model_dump(), added_by=str(current_user.id))
    await row.insert()
    return _json_doc(row)


@seed_router.post("/bulk", response_model=dict)
async def bulk_seed_import(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
) -> Any:
    raw = (await file.read()).decode("utf-8-sig")
    import csv
    from io import StringIO

    imported = 0
    skipped = 0
    invalid: list[str] = []
    for row in csv.DictReader(StringIO(raw)):
        try:
            domain = str(row.get("domain") or "").strip()
            if not domain:
                invalid.append(str(row))
                continue
            if await CompanySeed.find_one(CompanySeed.domain == domain):
                skipped += 1
                continue
            seed = CompanySeed(
                company_name=str(row.get("company_name") or row.get("name") or domain),
                domain=domain,
                careers_url=str(row.get("careers_url") or "").strip() or None,
                industry=str(row.get("industry") or "technology"),
                company_size=str(row.get("company_size") or "mid"),
                india_presence=str(row.get("india_presence") or "true").lower() != "false",
                student_friendly=str(row.get("student_friendly") or "true").lower() != "false",
                priority_tier=str(row.get("priority_tier") or "").strip() or None,
                source_category=str(row.get("source_category") or "").strip() or None,
                check_cadence_hours=int(row.get("check_cadence_hours") or 168),
                target_roles=[
                    item.strip()
                    for item in str(row.get("target_roles") or "internship,0-1 years,early career").split(",")
                    if item.strip()
                ],
                notes=str(row.get("notes") or "").strip() or None,
                added_by=str(current_user.id),
            )
            await seed.insert()
            imported += 1
        except Exception:
            invalid.append(str(row))
    return {"imported": imported, "skipped_duplicates": skipped, "invalid_rows": invalid}


@seed_router.delete("/{seed_id}", response_model=dict)
async def delete_seed(
    seed_id: PydanticObjectId,
    _: User = Depends(get_current_admin_user),
) -> Any:
    row = await CompanySeed.get(seed_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Seed not found")
    await row.delete()
    return {"status": "deleted", "seed_id": str(seed_id)}


@seed_router.get("/stats", response_model=dict)
async def seed_stats(_: User = Depends(get_current_admin_user)) -> Any:
    rows = await CompanySeed.find_many().to_list()
    promoted_ids = {
        str(row.id)
        for row in await DiscoveredSource.find_many(DiscoveredSource.status == SourceStatus.promoted).to_list()
    }
    return {
        "total_seeds": len(rows),
        "seeds_with_careers_url": sum(1 for row in rows if row.careers_url),
        "seeds_with_discovered_source": sum(1 for row in rows if row.discovered_source_id),
        "seeds_promoted_sources": sum(1 for row in rows if row.discovered_source_id in promoted_ids),
    }
