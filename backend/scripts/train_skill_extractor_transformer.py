from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

import joblib
import torch
from dotenv import dotenv_values
from huggingface_hub import HfApi, hf_hub_download
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForTokenClassification, AutoTokenizer, get_linear_schedule_with_warmup

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DATASET_ID = "jjzha/skillspan"
# JobBERT: BERT continued-pretrained on job postings by the SkillSpan author.
# Cased on purpose - most skills are proper nouns and an uncased model discards
# that before training. distilbert-base-uncased scored 0.538 test span F1 here.
BASE_MODEL = "jjzha/jobbert-base-cased"
LABEL_TO_ID = {"O": 0, "B": 1, "I": 2}
ID_TO_LABEL = {value: key for key, value in LABEL_TO_ID.items()}


def _hf_token() -> str | None:
    return (os.getenv("HF_TOKEN") or str(dotenv_values(REPO_ROOT / ".env").get("HF_TOKEN") or "")).strip() or None


def _load_split(filename: str, *, token: str, revision: str) -> list[dict[str, Any]]:
    path = Path(hf_hub_download(repo_id=DATASET_ID, repo_type="dataset", filename=filename, revision=revision, token=token))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tags(row: dict[str, Any]) -> list[str]:
    tokens = row.get("tokens") or []
    skill = row.get("tags_skill") or []
    knowledge = row.get("tags_knowledge") or []
    if not isinstance(tokens, list) or len(tokens) != len(skill) or len(tokens) != len(knowledge):
        raise ValueError("SkillSpan row has mismatched token and tag lengths")
    values: list[str] = []
    for skill_tag, knowledge_tag in zip(skill, knowledge):
        selected = str(skill_tag or "O")
        if selected == "O":
            selected = str(knowledge_tag or "O")
        values.append(selected if selected in {"B", "I"} else "O")
    return values


def _spans(tags: list[str]) -> set[tuple[int, int]]:
    spans: set[tuple[int, int]] = set()
    start: int | None = None
    for index, tag in enumerate(tags):
        if tag == "B":
            if start is not None:
                spans.add((start, index))
            start = index
        elif tag == "I" and start is None:
            start = index
        elif tag == "O" and start is not None:
            spans.add((start, index))
            start = None
    if start is not None:
        spans.add((start, len(tags)))
    return spans


def _metrics(actual: list[list[str]], predicted: list[list[str]]) -> dict[str, float]:
    true_positive = false_positive = false_negative = 0
    for expected_tags, predicted_tags in zip(actual, predicted):
        expected = _spans(expected_tags)
        observed = _spans(predicted_tags)
        true_positive += len(expected & observed)
        false_positive += len(observed - expected)
        false_negative += len(expected - observed)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    return {
        "span_precision": round(precision, 6),
        "span_recall": round(recall, 6),
        "span_f1": round(2 * precision * recall / max(1e-12, precision + recall), 6),
    }


class SkillSpanDataset(Dataset):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        return {"tokens": [str(token) for token in row["tokens"]], "tags": _tags(row)}


def _collate(tokenizer: Any, batch: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
    encoded = tokenizer(
        [item["tokens"] for item in batch],
        is_split_into_words=True,
        padding=True,
        truncation=True,
        max_length=128,
        return_tensors="pt",
    )
    aligned: list[list[int]] = []
    for index, item in enumerate(batch):
        previous_word: int | None = None
        labels: list[int] = []
        for word_id in encoded.word_ids(batch_index=index):
            if word_id is None or word_id == previous_word:
                labels.append(-100)
            else:
                labels.append(LABEL_TO_ID[item["tags"][word_id]])
            previous_word = word_id
        aligned.append(labels)
    encoded["labels"] = torch.tensor(aligned, dtype=torch.long)
    return dict(encoded)


def _word_predictions(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, Any]],
    *,
    device: torch.device,
    batch_size: int,
) -> list[list[tuple[str, float]]]:
    """Run the model once and return (label, probability) per word.

    Kept separate from thresholding because the confidence sweep used to call a
    row-at-a-time predict once per candidate threshold, re-running the whole dev
    split three times per epoch to score logits that never changed. Inference now
    happens once per epoch, batched, and each threshold is applied to the cached
    probabilities.
    """
    model.eval()
    output: list[list[tuple[str, float]]] = []
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            token_lists = [[str(token) for token in row["tokens"]] for row in chunk]
            encoded = tokenizer(
                token_lists,
                is_split_into_words=True,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            )
            inputs = {key: value.to(device) for key, value in encoded.items()}
            probabilities = torch.softmax(model(**inputs).logits, dim=-1).detach().cpu()
            for offset, tokens in enumerate(token_lists):
                # Default covers words truncated past max_length, which must score
                # as O rather than silently vanishing from the span comparison.
                per_word: list[tuple[str, float]] = [("O", 1.0)] * len(tokens)
                seen_words: set[int] = set()
                for index, word_id in enumerate(encoded.word_ids(batch_index=offset)):
                    if word_id is None or word_id in seen_words:
                        continue
                    seen_words.add(word_id)
                    probability, label_id = probabilities[offset][index].max(dim=-1)
                    per_word[word_id] = (ID_TO_LABEL[int(label_id)], float(probability))
                output.append(per_word)
    return output


def _apply_confidence(
    word_predictions: list[list[tuple[str, float]]], *, confidence: float
) -> list[list[str]]:
    return [
        [label if label in {"B", "I"} and probability >= confidence else "O" for label, probability in row]
        for row in word_predictions
    ]


def _predict(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, Any]],
    *,
    device: torch.device,
    confidence: float,
    batch_size: int = 32,
) -> list[list[str]]:
    return _apply_confidence(
        _word_predictions(model, tokenizer, rows, device=device, batch_size=batch_size),
        confidence=confidence,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune a guarded transformer skill-span extractor on SkillSpan.")
    parser.add_argument("--output", default="backend/models/skill_extractor.joblib")
    parser.add_argument("--model-dir", default="backend/models/skill_extractor_transformer")
    parser.add_argument("--report", default="backend/benchmarks/skill_extractor_transformer_latest.json")
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--eval-batch-size", type=int, default=32)
    parser.add_argument("--min-test-span-f1", type=float, default=0.5)
    parser.add_argument(
        "--base-model",
        default=BASE_MODEL,
        help=(
            "HF model id. Defaults to JobBERT, which is BERT continued-pretrained on "
            "job postings by the author of SkillSpan. Cased matters here: skills are "
            "mostly proper nouns (Python, SQL, AWS), and an uncased model throws that "
            "signal away before training starts."
        ),
    )
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument(
        "--warmup-ratio",
        type=float,
        default=0.1,
        help="Fraction of steps spent warming up before linear decay.",
    )
    parser.add_argument(
        "--confidences",
        default="0.34,0.4,0.45,0.5,0.55,0.6,0.7",
        help=(
            "Comma-separated decision thresholds swept on dev. Thresholding is free "
            "now that the sweep reuses one set of cached probabilities, but values at "
            "or below 1/num_labels are inert: the argmax class of a softmax over 3 "
            "labels always scores at least 1/3, so 0.05 through 0.33 all produce "
            "byte-identical predictions. Measured - 0.05 and 0.30 both gave dev F1 "
            "0.5834. The sweep therefore starts just above the floor."
        ),
    )
    args = parser.parse_args()
    confidences = tuple(
        sorted({float(value) for value in str(args.confidences).split(",") if value.strip()})
    )
    if not confidences:
        raise SystemExit("--confidences must contain at least one threshold")

    token = _hf_token()
    if not token:
        raise SystemExit("HF_TOKEN is required")
    api = HfApi(token=token)
    revision = str(api.dataset_info(DATASET_ID).sha or "main")
    splits = {"train": _load_split("train.json", token=token, revision=revision), "dev": _load_split("dev.json", token=token, revision=revision), "test": _load_split("test.json", token=token, revision=revision)}
    if min(len(rows) for rows in splits.values()) < 1_000:
        raise SystemExit("SkillSpan quality gate failed: incomplete split")

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    base_model = str(args.base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model, token=token)
    model = AutoModelForTokenClassification.from_pretrained(
        base_model,
        num_labels=len(LABEL_TO_ID),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
        token=token,
    ).to(device)
    loader = DataLoader(
        SkillSpanDataset(splits["train"]),
        batch_size=max(1, args.batch_size),
        shuffle=True,
        collate_fn=lambda batch: _collate(tokenizer, batch),
    )
    optimizer = AdamW(model.parameters(), lr=float(args.learning_rate))
    # A constant LR for the whole run left the model still moving at the last
    # step. Warmup then linear decay is the standard schedule for BERT-family
    # token classification and costs nothing.
    total_steps = max(1, len(loader) * max(1, args.epochs))
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * max(0.0, min(0.5, args.warmup_ratio))),
        num_training_steps=total_steps,
    )
    expected_dev = [_tags(row) for row in splits["dev"]]
    best_state: dict[str, torch.Tensor] | None = None
    best_selection: dict[str, float] | None = None
    for epoch in range(1, max(1, args.epochs) + 1):
        model.train()
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
        dev_word_predictions = _word_predictions(
            model, tokenizer, splits["dev"], device=device, batch_size=int(args.eval_batch_size)
        )
        for confidence in confidences:
            metrics = _metrics(expected_dev, _apply_confidence(dev_word_predictions, confidence=confidence))
            selection = {"epoch": float(epoch), "confidence": confidence, **metrics}
            print(
                f"epoch {epoch} conf {confidence:.2f}  "
                f"dev_f1={metrics['span_f1']:.4f} p={metrics['span_precision']:.4f} "
                f"r={metrics['span_recall']:.4f}",
                flush=True,
            )
            if best_selection is None or selection["span_f1"] > best_selection["span_f1"]:
                best_selection = selection
                best_state = copy.deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})

    assert best_state is not None and best_selection is not None
    model.load_state_dict(best_state)
    test_metrics = _metrics(
        [_tags(row) for row in splits["test"]],
        _predict(
            model,
            tokenizer,
            splits["test"],
            device=device,
            confidence=best_selection["confidence"],
            batch_size=int(args.eval_batch_size),
        ),
    )
    report = {
        "status": "approved" if test_metrics["span_f1"] >= args.min_test_span_f1 else "rejected",
        "dataset": {"id": DATASET_ID, "revision": revision, "license": "cc-by-4.0"},
        "base_model": base_model,
        "device": str(device),
        "splits": {name: len(rows) for name, rows in splits.items()},
        "selection": best_selection,
        "test": test_metrics,
        "minimum_test_span_f1": args.min_test_span_f1,
        "hyperparameters": {
            "epochs": int(args.epochs),
            "batch_size": int(args.batch_size),
            "learning_rate": float(args.learning_rate),
            "warmup_ratio": float(args.warmup_ratio),
            "confidences_swept": list(confidences),
        },
    }
    report_path = REPO_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["status"] != "approved":
        raise SystemExit(json.dumps(report, sort_keys=True))

    model_dir = REPO_ROOT / args.model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(model_dir)
    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "schema_version": 1,
            "model_type": "transformer",
            # Repo-relative so the artifact survives the checkout moving.
            # An absolute path here fails silently at load time: the loader
            # warns and degrades to keyword extraction.
            "model_dir": str(Path(args.model_dir)),
            "id_to_label": ID_TO_LABEL,
            "min_confidence": best_selection["confidence"],
            "dataset": report["dataset"],
            "test_metrics": test_metrics,
        },
        output_path,
    )
    print(json.dumps({**report, "artifact": str(output_path), "model_dir": str(model_dir)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
