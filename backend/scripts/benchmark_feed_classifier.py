"""Compare feed domain classifiers on a small regression fixture, without activating models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.ai_engine import AIEngine


def evaluate(rows, predict):
    results = []
    for row in rows:
        started = time.perf_counter()
        predicted = predict(row)
        results.append({
            "title": row["title"], "expected": row["domain"], "predicted": predicted,
            "correct": predicted == row["domain"], "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        })
    return {
        "cases": len(results), "correct": sum(row["correct"] for row in results),
        "median_latency_ms": statistics.median(row["latency_ms"] for row in results),
        "misses": [row for row in results if not row["correct"]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=BACKEND / "tests/fixtures/feed_domain_eval.json")
    parser.add_argument("--model")
    parser.add_argument("--revision")
    arguments = parser.parse_args()
    if arguments.model and not arguments.revision:
        parser.error("--revision is required when evaluating a Hugging Face model")
    rows = json.loads(arguments.dataset.read_text())
    if not rows:
        parser.error("dataset must contain labelled examples")
    engine = AIEngine()
    report = {
        "dataset": arguments.dataset.name,
        "evaluation_scope": "Small hand-labelled regression fixture; not a production accuracy estimate.",
        "incumbent": evaluate(rows, lambda row: engine.classify_opportunity(row["description"], title=row["title"])["primary_domain"]),
    }
    print(json.dumps(report, indent=2), flush=True)
    if arguments.model:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        torch.set_num_threads(4)
        options = {"revision": arguments.revision, "trust_remote_code": False, "token": False}
        tokenizer = AutoTokenizer.from_pretrained(arguments.model, **options)
        model = AutoModelForSequenceClassification.from_pretrained(arguments.model, use_safetensors=True, **options)
        classifier = pipeline("zero-shot-classification", model=model, tokenizer=tokenizer, device=-1)

        def predict(row):
            text = f"Role or event title: {row['title']}. Details: {row['description']}"[:3000]
            output = classifier(text, candidate_labels=engine.domains, hypothesis_template="This opportunity is in the field of {}.", multi_label=False, batch_size=8)
            return output["labels"][0]

        report["candidate"] = {"model": arguments.model, "revision": arguments.revision, **evaluate(rows, predict)}
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
