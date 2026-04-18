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
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.nlp_model_version import NLPModelVersion
from app.services.nlp_model_service import nlp_model_service


def _repo_root() -> Path:
    return BACKEND_ROOT.parent


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Row at {path}:{line_no} must be an object")
        rows.append(row)
    return rows


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Train and register an NLP intent/NER model version from JSONL examples.")
    parser.add_argument(
        "--dataset",
        type=str,
        default="backend/benchmarks/data/nlp_labeled_examples.jsonl",
        help="Path to JSONL dataset with rows: {text, intent, entities}.",
    )
    parser.add_argument("--name", type=str, default="nlp-model-v1", help="Model version name.")
    parser.add_argument("--notes", type=str, default="CLI-trained NLP model", help="Optional model notes.")
    parser.add_argument("--auto-activate", action="store_true", help="Activate the trained model if metric threshold passes.")
    parser.add_argument("--min-intent-macro-f1", type=float, default=0.55, help="Activation threshold for intent macro F1.")
    parser.add_argument(
        "--min-intent-macro-f1-uplift",
        type=float,
        default=0.0,
        help="Activation threshold for macro-F1 uplift over centroid baseline.",
    )
    parser.add_argument(
        "--ner-eval-dataset",
        type=str,
        default="backend/benchmarks/data/nlp_ner_eval_set.jsonl",
        help="Optional JSONL dataset for dedicated NER evaluation (same row schema).",
    )
    parser.add_argument("--linear-head-learning-rate", type=float, default=0.08, help="Learning rate for linear classifier head.")
    parser.add_argument("--linear-head-epochs", type=int, default=220, help="Training epochs for linear classifier head.")
    parser.add_argument("--linear-head-l2", type=float, default=0.0001, help="L2 regularization for linear classifier head.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = _repo_root() / dataset_path
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    ner_eval_rows: list[dict[str, Any]] | None = None
    ner_eval_path = Path(args.ner_eval_dataset)
    if not ner_eval_path.is_absolute():
        ner_eval_path = _repo_root() / ner_eval_path
    if ner_eval_path.exists():
        ner_eval_rows = _load_jsonl(ner_eval_path)

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[NLPModelVersion],
    )

    try:
        examples = _load_jsonl(dataset_path)
        model = await nlp_model_service.train_and_register(
            examples=examples,
            name=args.name,
            notes=args.notes,
            auto_activate=bool(args.auto_activate),
            min_intent_macro_f1_for_activation=float(args.min_intent_macro_f1),
            min_intent_macro_f1_uplift_for_activation=float(args.min_intent_macro_f1_uplift),
            ner_eval_examples=ner_eval_rows,
            linear_head_learning_rate=float(args.linear_head_learning_rate),
            linear_head_epochs=int(args.linear_head_epochs),
            linear_head_l2=float(args.linear_head_l2),
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "model_id": str(model.id),
                    "name": model.name,
                    "is_active": bool(model.is_active),
                    "metrics": model.metrics,
                    "evaluation_snapshot": model.evaluation_snapshot,
                    "training_rows": model.training_rows,
                    "dataset": str(dataset_path),
                    "ner_eval_dataset": str(ner_eval_path) if ner_eval_rows is not None else None,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(_main())
