from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.mlops.drift_service import drift_service
from app.services.mlops.retraining_service import retraining_service
from app.services.ranking_model_service import ranking_model_service
from scripts.publish_model_metadata import _build_metadata_markdown, _collect_snapshot, _save_artifact, _upsert_readme_section


def _model_score(model: RankingModelVersion) -> tuple[float, float, str]:
    metrics = dict(model.metrics or {})
    auc = float(metrics.get("auc_learned_test") or metrics.get("auc_learned") or 0.0)
    gain = float(metrics.get("auc_gain_test") or metrics.get("auc_gain") or 0.0)
    return auc, gain, model.created_at.isoformat()


async def _select_champion(*, max_models: int) -> RankingModelVersion | None:
    candidates = await RankingModelVersion.find_many().sort("-created_at").limit(max(1, int(max_models))).to_list()
    if not candidates:
        return None

    viable: list[RankingModelVersion] = []
    min_positive = float(max(0.0, min(1.0, settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE)))
    for model in candidates:
        metrics = dict(model.metrics or {})
        positive_rate = float(metrics.get("positive_rate") or 0.0)
        if positive_rate < min_positive:
            continue
        viable.append(model)

    if not viable:
        viable = candidates
    return sorted(viable, key=_model_score, reverse=True)[0]


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run ranking lifecycle pipeline: retrain -> champion activation -> drift -> publish metadata.")
    parser.add_argument("--lookback-days", type=int, default=int(settings.MLOPS_RETRAIN_LOOKBACK_DAYS))
    parser.add_argument("--label-window-hours", type=int, default=int(settings.MLOPS_LABEL_WINDOW_HOURS))
    parser.add_argument("--min-rows", type=int, default=int(settings.MLOPS_MIN_TRAINING_ROWS))
    parser.add_argument("--grid-step", type=float, default=float(settings.MLOPS_TRAIN_GRID_STEP))
    parser.add_argument("--activation-policy", type=str, default=str(settings.MLOPS_ACTIVATION_POLICY))
    parser.add_argument("--max-champion-candidates", type=int, default=20)
    parser.add_argument(
        "--artifact",
        type=str,
        default=str(BACKEND_ROOT / "benchmarks" / "model_lifecycle_latest.json"),
        help="Ranking lifecycle snapshot artifact output path.",
    )
    parser.add_argument(
        "--model-card-artifact",
        type=str,
        default=str(BACKEND_ROOT / "benchmarks" / "model_card_latest.json"),
        help="Champion model card artifact output path.",
    )
    parser.add_argument(
        "--readme",
        type=str,
        default=str(REPO_ROOT / "README.md"),
        help="README file updated between MODEL_VERSION_METADATA markers.",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            RankingModelVersion,
            ModelDriftReport,
            OpportunityInteraction,
            RankingRequestTelemetry,
        ],
    )

    try:
        train_result = await retraining_service.retrain_and_register(
            lookback_days=int(args.lookback_days),
            label_window_hours=int(args.label_window_hours),
            min_rows=int(args.min_rows),
            grid_step=float(args.grid_step),
            auto_activate=True,
            activation_policy=str(args.activation_policy),
            min_auc_gain_for_activation=float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN),
            min_positive_rate_for_activation=float(settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE),
            max_weight_shift_for_activation=float(settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT),
            notes="lifecycle_pipeline",
        )

        champion = await _select_champion(max_models=int(args.max_champion_candidates))
        champion_id = None
        if champion is not None:
            champion_id = str(champion.id)
            if not bool(champion.is_active):
                champion = await ranking_model_service.activate(model_id=champion_id)

        drift_report = await drift_service.run(lookback_days=int(settings.MLOPS_DRIFT_LOOKBACK_DAYS))

        snapshot = await _collect_snapshot(max_models=max(5, int(args.max_champion_candidates)))
        artifact_path = Path(args.artifact)
        _save_artifact(artifact_path, snapshot)

        markdown = _build_metadata_markdown(snapshot)
        readme_ok = _upsert_readme_section(readme_path=Path(args.readme), markdown=markdown)
        if not readme_ok:
            raise RuntimeError("README metadata markers missing")

        if champion is not None:
            model_card_path = Path(args.model_card_artifact)
            model_card_path.parent.mkdir(parents=True, exist_ok=True)
            model_card_path.write_text(json.dumps(champion.model_card or {}, indent=2), encoding="utf-8")

        result_payload = {
            "status": "ok",
            "trained_rows": int(train_result.training_rows),
            "auto_activated": bool(train_result.auto_activated),
            "activation_reason": str(train_result.activation_reason),
            "champion_model_id": champion_id,
            "drift_report_id": str(drift_report.id),
            "artifact": str(artifact_path),
            "readme": str(Path(args.readme)),
            "model_card_artifact": str(Path(args.model_card_artifact)),
        }
        print(json.dumps(result_payload, indent=2, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
