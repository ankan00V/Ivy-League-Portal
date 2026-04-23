from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from beanie import PydanticObjectId

from app.core.config import settings
from app.models.experiment import Experiment, ExperimentVariant
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.rag_template_evaluation_run import RAGTemplateEvaluationRun
from app.models.rag_template_version import RAGTemplateVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.experiment_service import experiment_service
from app.services.ranking_metrics import normalize_relevant_ids, precision_at_k, recall_at_k
from app.services.vector_service import opportunity_vector_service

RAG_TEMPLATE_EXPERIMENT_KEY = "ask_ai_rag_template"


@dataclass(frozen=True)
class RAGTemplateResolution:
    template: RAGTemplateVersion
    experiment_key: Optional[str]
    experiment_variant: Optional[str]
    assigned_via_experiment: bool


def _default_system_prompt() -> str:
    return (
        "You are an opportunity-shortlisting assistant. "
        "Return STRICT JSON only (no markdown). "
        "Schema:\n"
        "- summary: string\n"
        "- top_opportunities: array (max 3) of {opportunity_id, title, why_fit, urgency(low|medium|high), match_score(0-100), citations}\n"
        "- deadline_urgency: string\n"
        "- recommended_action: string\n"
        "- citations: array of {opportunity_id, url}\n"
        "- safety: {hallucination_checks_passed, failed_checks}\n"
        "Rules:\n"
        "- Only use opportunity_id values from candidates.\n"
        "- Every top_opportunity MUST include citations with the matching opportunity_id and url.\n"
        "- citations must reference retrieved candidates (id + url)."
    )


def _default_judge_rubric() -> str:
    return (
        "Score 0..1 for groundedness to retrieved candidates, shortlisting usefulness, and clarity. "
        "Penalize any invented opportunity IDs, invalid citations, or non-actionable summaries."
    )


class RAGTemplateRegistryService:
    async def ensure_defaults(self) -> None:
        template = await RAGTemplateVersion.find_one(
            RAGTemplateVersion.template_key == settings.RAG_TEMPLATE_KEY_DEFAULT,
            RAGTemplateVersion.is_active == True,  # noqa: E712
        )
        if not template:
            existing = await RAGTemplateVersion.find_many(
                RAGTemplateVersion.template_key == settings.RAG_TEMPLATE_KEY_DEFAULT
            ).sort("-version").to_list()
            next_version = int(existing[0].version + 1) if existing else 1
            label = f"{settings.RAG_TEMPLATE_KEY_DEFAULT}.v{next_version}"
            template = RAGTemplateVersion(
                template_key=settings.RAG_TEMPLATE_KEY_DEFAULT,
                label=label,
                version=next_version,
                description="Default production RAG template.",
                status="active",
                is_active=True,
                is_online_candidate=True,
                retrieval_top_k=max(1, int(settings.RAG_DEFAULT_RETRIEVAL_TOP_K)),
                retrieval_settings={},
                system_prompt=_default_system_prompt(),
                judge_rubric=_default_judge_rubric(),
                acceptance_thresholds={
                    "min_recall_at_k": float(settings.RAG_OFFLINE_MIN_RECALL_AT_K),
                    "min_judge_score": float(settings.LLM_JUDGE_MIN_SCORE),
                    "min_feedback_positive_rate": float(settings.RAG_ONLINE_MIN_POSITIVE_FEEDBACK_RATE),
                    "min_online_requests": float(settings.RAG_ONLINE_MIN_REQUESTS),
                },
                metadata={"seeded_by": "ensure_defaults"},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            await template.insert()

        await self._ensure_online_experiment([template.label])

    async def _ensure_online_experiment(self, labels: list[str]) -> None:
        variants = [
            ExperimentVariant(name=label, weight=1.0, is_control=(idx == 0))
            for idx, label in enumerate(labels)
        ]
        experiment = await Experiment.find_one(Experiment.key == RAG_TEMPLATE_EXPERIMENT_KEY)
        if not experiment:
            experiment = Experiment(
                key=RAG_TEMPLATE_EXPERIMENT_KEY,
                description="Online A/B for RAG prompt+retrieval templates.",
                status="active",
                variants=variants,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            await experiment.insert()
            return
        if sorted(v.name for v in experiment.variants) != sorted(labels):
            experiment.variants = variants
            experiment.updated_at = datetime.utcnow()
            await experiment.save()

    async def list_templates(self, *, template_key: str | None = None) -> list[RAGTemplateVersion]:
        if template_key:
            return await RAGTemplateVersion.find_many(RAGTemplateVersion.template_key == template_key).sort("-version").to_list()
        return await RAGTemplateVersion.find_many().sort("-updated_at").to_list()

    async def create_template(
        self,
        *,
        template_key: str,
        description: str | None,
        retrieval_top_k: int,
        retrieval_settings: dict[str, Any] | None,
        system_prompt: str,
        judge_rubric: str,
        acceptance_thresholds: dict[str, float] | None,
        is_online_candidate: bool,
    ) -> RAGTemplateVersion:
        key = (template_key or settings.RAG_TEMPLATE_KEY_DEFAULT).strip() or settings.RAG_TEMPLATE_KEY_DEFAULT
        existing = await RAGTemplateVersion.find_many(RAGTemplateVersion.template_key == key).sort("-version").to_list()
        next_version = int(existing[0].version + 1) if existing else 1
        label = f"{key}.v{next_version}"
        template = RAGTemplateVersion(
            template_key=key,
            label=label,
            version=next_version,
            description=(description or "").strip() or None,
            status="draft",
            is_active=False,
            is_online_candidate=bool(is_online_candidate),
            retrieval_top_k=max(1, min(int(retrieval_top_k), 50)),
            retrieval_settings=dict(retrieval_settings or {}),
            system_prompt=system_prompt.strip(),
            judge_rubric=judge_rubric.strip(),
            acceptance_thresholds={
                "min_recall_at_k": float((acceptance_thresholds or {}).get("min_recall_at_k", settings.RAG_OFFLINE_MIN_RECALL_AT_K)),
                "min_judge_score": float((acceptance_thresholds or {}).get("min_judge_score", settings.LLM_JUDGE_MIN_SCORE)),
                "min_feedback_positive_rate": float(
                    (acceptance_thresholds or {}).get("min_feedback_positive_rate", settings.RAG_ONLINE_MIN_POSITIVE_FEEDBACK_RATE)
                ),
                "min_online_requests": float((acceptance_thresholds or {}).get("min_online_requests", settings.RAG_ONLINE_MIN_REQUESTS)),
            },
            metadata={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await template.insert()
        return template

    async def activate_template(self, *, template_id: str) -> RAGTemplateVersion:
        template = await RAGTemplateVersion.get(template_id)
        if not template:
            raise ValueError("template_not_found")

        active_versions = await RAGTemplateVersion.find_many(
            RAGTemplateVersion.template_key == template.template_key,
            RAGTemplateVersion.is_active == True,  # noqa: E712
        ).to_list()
        for item in active_versions:
            if str(item.id) == str(template.id):
                continue
            item.is_active = False
            item.status = "draft" if item.status == "active" else item.status
            item.updated_at = datetime.utcnow()
            await item.save()

        template.is_active = True
        template.status = "active"
        template.updated_at = datetime.utcnow()
        await template.save()

        online_labels = [
            item.label
            for item in await RAGTemplateVersion.find_many(
                RAGTemplateVersion.template_key == template.template_key,
                RAGTemplateVersion.is_online_candidate == True,  # noqa: E712
                RAGTemplateVersion.status != "archived",
            ).sort("version").to_list()
        ]
        if template.label not in online_labels:
            online_labels.append(template.label)
        await self._ensure_online_experiment(online_labels)
        return template

    async def resolve_template(
        self,
        *,
        user_id: Optional[PydanticObjectId],
        template_key: str | None = None,
    ) -> RAGTemplateResolution:
        key = (template_key or settings.RAG_TEMPLATE_KEY_DEFAULT).strip() or settings.RAG_TEMPLATE_KEY_DEFAULT
        active_template = await RAGTemplateVersion.find_one(
            RAGTemplateVersion.template_key == key,
            RAGTemplateVersion.is_active == True,  # noqa: E712
        )
        if not active_template:
            await self.ensure_defaults()
            active_template = await RAGTemplateVersion.find_one(
                RAGTemplateVersion.template_key == key,
                RAGTemplateVersion.is_active == True,  # noqa: E712
            )
        if not active_template:
            raise RuntimeError("no_active_rag_template")

        if user_id is None:
            return RAGTemplateResolution(
                template=active_template,
                experiment_key=None,
                experiment_variant=None,
                assigned_via_experiment=False,
            )

        decision = await experiment_service.assign(user_id=user_id, experiment_key=RAG_TEMPLATE_EXPERIMENT_KEY)
        if not decision:
            return RAGTemplateResolution(
                template=active_template,
                experiment_key=None,
                experiment_variant=None,
                assigned_via_experiment=False,
            )
        variant_label = (decision.variant or "").strip()
        variant_template = await RAGTemplateVersion.find_one(
            RAGTemplateVersion.label == variant_label,
            RAGTemplateVersion.template_key == key,
            RAGTemplateVersion.status != "archived",
        )
        if not variant_template:
            variant_template = active_template
            variant_label = variant_template.label

        return RAGTemplateResolution(
            template=variant_template,
            experiment_key=decision.experiment_key,
            experiment_variant=variant_label,
            assigned_via_experiment=True,
        )

    async def evaluate_offline(self, *, template_id: str, dataset_path: str | None = None) -> RAGTemplateEvaluationRun:
        template = await RAGTemplateVersion.get(template_id)
        if not template:
            raise ValueError("template_not_found")

        path = Path(dataset_path or settings.RAG_OFFLINE_EVAL_DATASET_PATH)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[3]
            path = repo_root / path
        if not path.exists():
            raise FileNotFoundError(f"Offline dataset missing: {path}")

        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            rows.append(json.loads(raw))
        if not rows:
            raise ValueError("offline_dataset_empty")

        top_k = max(1, min(int(template.retrieval_top_k), 50))
        recalls: list[float] = []
        precisions: list[float] = []
        for row in rows:
            query = str(row.get("query") or "").strip()
            relevant = normalize_relevant_ids(row.get("relevant_ids") or row.get("relevant_opportunity_ids") or [])
            if not query or not relevant:
                continue
            retrieved = await opportunity_vector_service.search(query, top_k=top_k)
            ranked_ids = [str(item.get("id") or "") for item in retrieved if str(item.get("id") or "").strip()]
            recalls.append(float(recall_at_k(ranked_ids, relevant, top_k)))
            precisions.append(float(precision_at_k(ranked_ids, relevant, top_k)))

        mean_recall = float(sum(recalls) / max(1, len(recalls)))
        mean_precision = float(sum(precisions) / max(1, len(precisions)))
        thresholds = dict(template.acceptance_thresholds or {})
        min_recall = float(thresholds.get("min_recall_at_k", settings.RAG_OFFLINE_MIN_RECALL_AT_K))
        accepted = mean_recall >= min_recall

        run = RAGTemplateEvaluationRun(
            template_key=template.template_key,
            template_label=template.label,
            template_version_id=str(template.id),
            mode="offline",
            metrics={
                "queries_evaluated": len(recalls),
                "retrieval_top_k": top_k,
                "recall_at_k": round(mean_recall, 8),
                "precision_at_k": round(mean_precision, 8),
            },
            thresholds={
                "min_recall_at_k": min_recall,
            },
            accepted=bool(accepted),
            notes=None if accepted else "Offline recall below threshold",
            created_at=datetime.utcnow(),
        )
        await run.insert()
        return run

    async def evaluate_online(self, *, template_id: str, days: int = 14) -> RAGTemplateEvaluationRun:
        template = await RAGTemplateVersion.get(template_id)
        if not template:
            raise ValueError("template_not_found")

        safe_days = max(1, min(int(days), 90))
        since = datetime.utcnow() - timedelta(days=safe_days)
        telemetry = await RankingRequestTelemetry.find_many(
            RankingRequestTelemetry.request_kind == "ask_ai",
            RankingRequestTelemetry.created_at >= since,
            RankingRequestTelemetry.rag_template_label == template.label,
            RankingRequestTelemetry.traffic_type == "real",
        ).to_list()
        feedback = await RAGFeedbackEvent.find_many(
            RAGFeedbackEvent.created_at >= since,
            RAGFeedbackEvent.rag_template_label == template.label,
        ).to_list()
        if not feedback:
            # Backward compatibility for older feedback rows that only stored template label in metadata.
            fallback_feedback = await RAGFeedbackEvent.find_many(RAGFeedbackEvent.created_at >= since).to_list()
            feedback = [
                row
                for row in fallback_feedback
                if str((row.metadata or {}).get("rag_template_label") or (row.metadata or {}).get("template_label") or "").strip()
                == template.label
            ]

        request_count = len(telemetry)
        success_count = sum(1 for item in telemetry if bool(item.success))
        avg_latency = _safe_mean([float(item.latency_ms) for item in telemetry])
        failure_rate = 1.0 - _safe_ratio(success_count, request_count)

        up_votes = sum(1 for item in feedback if str(item.feedback).lower() == "up")
        down_votes = sum(1 for item in feedback if str(item.feedback).lower() == "down")
        total_votes = up_votes + down_votes
        positive_rate = _safe_ratio(up_votes, total_votes)

        thresholds = dict(template.acceptance_thresholds or {})
        min_requests = int(max(1, thresholds.get("min_online_requests", settings.RAG_ONLINE_MIN_REQUESTS)))
        min_positive_rate = float(
            max(0.0, min(1.0, thresholds.get("min_feedback_positive_rate", settings.RAG_ONLINE_MIN_POSITIVE_FEEDBACK_RATE)))
        )
        accepted = request_count >= min_requests and positive_rate >= min_positive_rate

        run = RAGTemplateEvaluationRun(
            template_key=template.template_key,
            template_label=template.label,
            template_version_id=str(template.id),
            mode="online",
            metrics={
                "days": safe_days,
                "request_count": request_count,
                "success_count": success_count,
                "failure_rate": round(float(failure_rate), 8),
                "avg_latency_ms": round(float(avg_latency), 8),
                "feedback_up": up_votes,
                "feedback_down": down_votes,
                "feedback_positive_rate": round(float(positive_rate), 8),
            },
            thresholds={
                "min_online_requests": float(min_requests),
                "min_feedback_positive_rate": min_positive_rate,
            },
            accepted=bool(accepted),
            notes=None if accepted else "Online threshold gate failed",
            created_at=datetime.utcnow(),
        )
        await run.insert()
        return run

    async def list_evaluations(self, *, template_id: str) -> list[RAGTemplateEvaluationRun]:
        template = await RAGTemplateVersion.get(template_id)
        if not template:
            return []
        return await RAGTemplateEvaluationRun.find_many(
            RAGTemplateEvaluationRun.template_version_id == str(template.id)
        ).sort("-created_at").to_list()


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


rag_template_registry_service = RAGTemplateRegistryService()
