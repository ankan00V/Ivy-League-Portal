from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import joblib
from dotenv import dotenv_values
from huggingface_hub import HfApi, hf_hub_download
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.skill_extractor import DEFAULT_SKILL_TAGS, token_feature_rows

DATASET_ID = "jjzha/skillspan"
SPLIT_FILES = {"train": "train.json", "dev": "dev.json", "test": "test.json"}


def _hf_token() -> str | None:
    configured = (os.getenv("HF_TOKEN") or "").strip()
    if configured:
        return configured
    token = str(dotenv_values(REPO_ROOT / ".env").get("HF_TOKEN") or "").strip()
    return token or None


def _download_splits() -> tuple[dict[str, list[dict[str, Any]]], str]:
    token = _hf_token()
    if not token:
        raise RuntimeError("HF_TOKEN is required to download SkillSpan")
    api = HfApi(token=token)
    revision = str(api.dataset_info(DATASET_ID).sha or "main")
    payload: dict[str, list[dict[str, Any]]] = {}
    for split, filename in SPLIT_FILES.items():
        path = Path(
            hf_hub_download(
                repo_id=DATASET_ID,
                repo_type="dataset",
                filename=filename,
                revision=revision,
                token=token,
            )
        )
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            raise ValueError(f"SkillSpan {split} split is empty")
        payload[split] = rows
    return payload, revision


def _merged_tags(row: dict[str, Any]) -> list[str]:
    tokens = row.get("tokens") or []
    skill = row.get("tags_skill") or []
    knowledge = row.get("tags_knowledge") or []
    if not isinstance(tokens, list) or len(tokens) != len(skill) or len(tokens) != len(knowledge):
        raise ValueError("SkillSpan row has mismatched token and tag lengths")
    merged: list[str] = []
    for skill_tag, knowledge_tag in zip(skill, knowledge):
        tag = str(skill_tag or "O")
        if tag == "O":
            tag = str(knowledge_tag or "O")
        merged.append(tag if tag in {"B", "I"} else "O")
    return merged


def _examples(rows: Iterable[dict[str, Any]]) -> tuple[list[str], list[str], list[list[str]]]:
    features: list[str] = []
    labels: list[str] = []
    documents: list[list[str]] = []
    for row in rows:
        tokens = [str(token) for token in row["tokens"]]
        tags = _merged_tags(row)
        features.extend(token_feature_rows(tokens))
        labels.extend(tags)
        documents.append(tags)
    return features, labels, documents


def _spans(tags: list[str]) -> set[tuple[int, int]]:
    results: set[tuple[int, int]] = set()
    start: int | None = None
    for index, tag in enumerate(tags):
        if tag == "B":
            if start is not None:
                results.add((start, index))
            start = index
        elif tag != "I" and start is not None:
            results.add((start, index))
            start = None
        elif tag == "I" and start is None:
            start = index
    if start is not None:
        results.add((start, len(tags)))
    return results


def _metrics(true_documents: list[list[str]], predicted_documents: list[list[str]]) -> dict[str, float]:
    true_positive = false_positive = false_negative = 0
    for actual, predicted in zip(true_documents, predicted_documents):
        actual_spans = _spans(actual)
        predicted_spans = _spans(predicted)
        true_positive += len(actual_spans & predicted_spans)
        false_positive += len(predicted_spans - actual_spans)
        false_negative += len(actual_spans - predicted_spans)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    return {
        "span_precision": round(precision, 6),
        "span_recall": round(recall, 6),
        "span_f1": round((2 * precision * recall / max(1e-12, precision + recall)), 6),
    }


def _predict_documents(
    pipeline: Pipeline,
    rows: list[dict[str, Any]],
    *,
    confidence: float,
) -> list[list[str]]:
    predictions: list[list[str]] = []
    classes = [str(value) for value in pipeline.classes_]
    for row in rows:
        tokens = [str(token) for token in row["tokens"]]
        probabilities = pipeline.predict_proba(token_feature_rows(tokens))
        tags: list[str] = []
        for probability in probabilities:
            index = int(probability.argmax())
            label = classes[index]
            tags.append(label if label in {"B", "I"} and float(probability[index]) >= confidence else "O")
        predictions.append(tags)
    return predictions


def _keyword_baseline(rows: list[dict[str, Any]]) -> list[list[str]]:
    known = [skill.split() for skill in DEFAULT_SKILL_TAGS]
    predictions: list[list[str]] = []
    for row in rows:
        tokens = [str(token).lower() for token in row["tokens"]]
        tags = ["O"] * len(tokens)
        for phrase in known:
            width = len(phrase)
            for index in range(max(0, len(tokens) - width + 1)):
                if tokens[index : index + width] == phrase:
                    tags[index] = "B"
                    for offset in range(1, width):
                        tags[index + offset] = "I"
        predictions.append(tags)
    return predictions


def _skill_lexicon(rows: list[dict[str, Any]]) -> list[str]:
    phrases: set[str] = set()
    for row in rows:
        tokens = [str(token).lower() for token in row["tokens"]]
        for start, end in _spans(_merged_tags(row)):
            phrase = " ".join(tokens[start:end]).strip()
            if phrase and len(phrase.split()) <= 8:
                phrases.add(phrase)
    return sorted(phrases, key=lambda value: (-len(value.split()), value))


def _lexicon_predictions(rows: list[dict[str, Any]], phrases: list[str]) -> list[list[str]]:
    phrase_tokens = [phrase.split() for phrase in phrases]
    predictions: list[list[str]] = []
    for row in rows:
        tokens = [str(token).lower() for token in row["tokens"]]
        tags = ["O"] * len(tokens)
        index = 0
        while index < len(tokens):
            matched = next(
                (phrase for phrase in phrase_tokens if tokens[index : index + len(phrase)] == phrase),
                None,
            )
            if matched is None:
                index += 1
                continue
            tags[index] = "B"
            for offset in range(1, len(matched)):
                tags[index + offset] = "I"
            index += len(matched)
        predictions.append(tags)
    return predictions


def _merge_predictions(primary: list[list[str]], secondary: list[list[str]]) -> list[list[str]]:
    merged: list[list[str]] = []
    for primary_tags, secondary_tags in zip(primary, secondary):
        merged.append([first if first != "O" else second for first, second in zip(primary_tags, secondary_tags)])
    return merged


def _make_pipeline(*, regularization: float) -> Pipeline:
    return Pipeline(
        [
            (
                "vectorizer",
                TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=60_000, sublinear_tf=True),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=regularization,
                    class_weight="balanced",
                    max_iter=400,
                    random_state=42,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a guarded SkillSpan token classifier for source-discovery tags.")
    parser.add_argument("--output", default="backend/models/skill_extractor.joblib")
    parser.add_argument("--report", default="backend/benchmarks/skill_extractor_latest.json")
    parser.add_argument("--min-test-span-f1", type=float, default=0.35)
    args = parser.parse_args()

    splits, revision = _download_splits()
    train_features, train_labels, _train_documents = _examples(splits["train"])
    _dev_features, _dev_labels, dev_documents = _examples(splits["dev"])
    _test_features, _test_labels, test_documents = _examples(splits["test"])
    if len(train_features) < 10_000 or len(set(train_labels)) != 3:
        raise SystemExit("SkillSpan quality gate failed: insufficient training volume or incomplete BIO labels")

    best: tuple[float, float, Pipeline, dict[str, float]] | None = None
    train_lexicon = _skill_lexicon(splits["train"])
    dev_lexicon_predictions = _lexicon_predictions(splits["dev"], train_lexicon)
    for regularization in (0.5, 1.0, 2.0):
        pipeline = _make_pipeline(regularization=regularization)
        pipeline.fit(train_features, train_labels)
        for confidence in (0.45, 0.55, 0.65, 0.75):
            predictions = _merge_predictions(
                dev_lexicon_predictions,
                _predict_documents(pipeline, splits["dev"], confidence=confidence),
            )
            metrics = _metrics(dev_documents, predictions)
            candidate = (metrics["span_f1"], regularization, pipeline, {**metrics, "confidence": confidence})
            if best is None or candidate[0] > best[0]:
                best = candidate

    assert best is not None
    _dev_f1, regularization, _dev_pipeline, dev_metrics = best
    combined_features = train_features + _dev_features
    combined_labels = train_labels + _dev_labels
    final_pipeline = _make_pipeline(regularization=regularization)
    final_pipeline.fit(combined_features, combined_labels)
    final_lexicon = _skill_lexicon(splits["train"] + splits["dev"])
    test_predictions = _merge_predictions(
        _lexicon_predictions(splits["test"], final_lexicon),
        _predict_documents(final_pipeline, splits["test"], confidence=dev_metrics["confidence"]),
    )
    test_metrics = _metrics(test_documents, test_predictions)
    baseline_metrics = _metrics(test_documents, _keyword_baseline(splits["test"]))

    report = {
        "status": "approved" if test_metrics["span_f1"] >= args.min_test_span_f1 else "rejected",
        "dataset": {"id": DATASET_ID, "revision": revision, "license": "cc-by-4.0"},
        "splits": {name: len(rows) for name, rows in splits.items()},
        "selection": {"regularization": regularization, **dev_metrics},
        "test": test_metrics,
        "keyword_baseline_test": baseline_metrics,
        "minimum_test_span_f1": args.min_test_span_f1,
    }
    report_path = REPO_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["status"] != "approved":
        raise SystemExit(json.dumps(report, sort_keys=True))

    output_path = REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "schema_version": 1,
            "dataset": report["dataset"],
            "pipeline": final_pipeline,
            "skill_lexicon": final_lexicon,
            "min_confidence": dev_metrics["confidence"],
            "test_metrics": test_metrics,
        },
        output_path,
    )
    print(json.dumps({**report, "artifact": str(output_path)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
