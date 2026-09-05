"""Precision and recall for the pay-to-apply detector.

The detector's job is one question: does this posting ask the reader to send
money? Not "does it mention payments" - a Paytm or Razorpay internship mentions
payments constantly and is a legitimate job.

The evaluation set is 400 real listings plus a small synthetic block. The live
corpus contains zero genuine pay-to-apply postings, so recall cannot be measured
from it at all; the synthetic fraud examples exist only to make recall
measurable, and the legit-fintech examples are the false-positive case that
motivated this. Every synthetic row is flagged as such in the data.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.opportunity_trust import assess_opportunity_trust, REVIEW_RISK_SCORE


def run() -> dict:
    rows = [json.loads(l) for l in open(Path(__file__).parent / "data/scam_posting_eval.jsonl")]
    tp = fp = tn = fn = 0
    fp_examples, fn_examples = [], []
    for r in rows:
        assessment = assess_opportunity_trust(r)
        flagged = assessment.risk_score >= REVIEW_RISK_SCORE
        truth = bool(r["label_demands_payment"])
        if flagged and truth: tp += 1
        elif flagged and not truth:
            fp += 1
            if len(fp_examples) < 5: fp_examples.append(r["title"])
        elif not flagged and truth:
            fn += 1
            if len(fn_examples) < 5: fn_examples.append(r["title"])
        else: tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision,
            "recall": recall, "f1": f1, "fp_examples": fp_examples, "fn_examples": fn_examples}


if __name__ == "__main__":
    m = run()
    print(f"  tp={m['tp']}  fp={m['fp']}  tn={m['tn']}  fn={m['fn']}")
    print(f"  precision={m['precision']:.2f}  recall={m['recall']:.2f}  f1={m['f1']:.2f}")
    if m["fp_examples"]: print("  false positives:", "; ".join(x[:38] for x in m["fp_examples"]))
    if m["fn_examples"]: print("  missed fraud   :", "; ".join(x[:38] for x in m["fn_examples"]))
