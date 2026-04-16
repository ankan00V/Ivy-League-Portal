from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Make the benchmark deterministic and dependency-light in CI:
# - Force hash embeddings (no sentence-transformers, no network).
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("OPENAI_API_KEY", "")


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")


@dataclass(frozen=True)
class OpportunityFixture:
    id: str
    title: str
    description: str
    domain: str | None = None
    opportunity_type: str | None = None
    university: str | None = None

    def to_text(self) -> str:
        return " ".join(
            [
                self.title or "",
                self.description or "",
                self.domain or "",
                self.opportunity_type or "",
                self.university or "",
            ]
        ).strip()


@dataclass(frozen=True)
class GoldQuery:
    query: str
    relevant_ids: list[str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_path(relative: str) -> Path:
    return _repo_root() / relative


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
    return rows


def load_opportunities(path: Path) -> list[OpportunityFixture]:
    raw_rows = _load_jsonl(path)
    items: list[OpportunityFixture] = []
    seen: set[str] = set()
    for row in raw_rows:
        opp_id = str(row.get("id") or "").strip()
        if not opp_id:
            raise ValueError(f"Opportunity missing id in {path}")
        if opp_id in seen:
            raise ValueError(f"Duplicate opportunity id={opp_id} in {path}")
        seen.add(opp_id)
        items.append(
            OpportunityFixture(
                id=opp_id,
                title=str(row.get("title") or ""),
                description=str(row.get("description") or ""),
                domain=row.get("domain"),
                opportunity_type=row.get("opportunity_type"),
                university=row.get("university"),
            )
        )
    if not items:
        raise ValueError(f"No opportunities loaded from {path}")
    return items


def load_gold(path: Path) -> list[GoldQuery]:
    raw_rows = _load_jsonl(path)
    items: list[GoldQuery] = []
    for row in raw_rows:
        query = str(row.get("query") or "").strip()
        relevant = row.get("relevant_ids") or row.get("relevant_opportunity_ids") or []
        if not query:
            raise ValueError(f"Gold row missing query in {path}")
        if not isinstance(relevant, list):
            raise ValueError(f"Gold row relevant_ids must be list in {path} for query={query!r}")
        items.append(GoldQuery(query=query, relevant_ids=[str(v) for v in relevant if v]))
    if not items:
        raise ValueError(f"No gold queries loaded from {path}")
    return items


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) >= 2}


def _lexical_score(query: str, opportunity_text: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    o = _tokens(opportunity_text)
    if not o:
        return 0.0
    overlap = len(q.intersection(o))
    return float(overlap)


def _sort_ids_by_score(ids: list[str], scores: list[float]) -> list[str]:
    paired = list(zip(ids, scores))
    paired.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return [item[0] for item in paired]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    safe_q = max(0.0, min(100.0, float(q)))
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (safe_q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _latency_summary(values_ms: list[float]) -> dict[str, float]:
    if not values_ms:
        return {
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }
    return {
        "mean": round(sum(values_ms) / float(len(values_ms)), 6),
        "p50": round(_percentile(values_ms, 50.0), 6),
        "p95": round(_percentile(values_ms, 95.0), 6),
        "max": round(max(values_ms), 6),
    }


async def _run(
    *,
    opportunities: list[OpportunityFixture],
    gold: list[GoldQuery],
    k: int,
) -> dict[str, Any]:
    # Import after env vars are set.
    repo_root = _repo_root()
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from app.services.embedding_service import embedding_service
    from app.services.ranking_metrics import mrr, ndcg_at_k, normalize_relevant_ids, precision_at_k, recall_at_k

    safe_k = max(1, min(int(k), 50))

    opp_ids = [opp.id for opp in opportunities]
    opp_texts = [opp.to_text() for opp in opportunities]
    opp_vectors = await embedding_service.embed_texts(opp_texts)

    mode_metrics: dict[str, list[dict[str, float]]] = {"baseline": [], "semantic": []}
    latency_ms: dict[str, list[float]] = {"baseline": [], "semantic": []}
    per_query: list[dict[str, Any]] = []

    for item in gold:
        relevant = normalize_relevant_ids(item.relevant_ids)

        # Baseline ranking (lexical query token overlap)
        t0 = time.perf_counter()
        baseline_scores = [_lexical_score(item.query, text) for text in opp_texts]
        baseline_ranked = _sort_ids_by_score(opp_ids, baseline_scores)
        latency_ms["baseline"].append((time.perf_counter() - t0) * 1000.0)

        # Semantic ranking (hash embeddings -> cosine)
        t1 = time.perf_counter()
        q_vec = await embedding_service.embed_text(item.query)
        sim_scores = (opp_vectors @ q_vec).tolist()
        semantic_ranked = _sort_ids_by_score(opp_ids, [float(v) for v in sim_scores])
        latency_ms["semantic"].append((time.perf_counter() - t1) * 1000.0)

        query_row: dict[str, Any] = {"query": item.query, "relevant_count": len(relevant), "modes": {}}
        for mode, ranked in (("baseline", baseline_ranked), ("semantic", semantic_ranked)):
            metrics = {
                "precision_at_k": float(precision_at_k(ranked, relevant, safe_k)),
                "recall_at_k": float(recall_at_k(ranked, relevant, safe_k)),
                "ndcg_at_k": float(ndcg_at_k(ranked, relevant, safe_k)),
                "mrr": float(mrr(ranked, relevant, safe_k)),
            }
            mode_metrics[mode].append(metrics)
            query_row["modes"][mode] = metrics

        per_query.append(query_row)

    def _mean(values: list[float]) -> float:
        return (sum(values) / float(len(values))) if values else 0.0

    summary: dict[str, Any] = {
        "k": safe_k,
        "query_count": len(gold),
        "modes": {},
    }
    for mode, rows in mode_metrics.items():
        summary["modes"][mode] = {
            "precision_at_k": round(_mean([r["precision_at_k"] for r in rows]), 6),
            "recall_at_k": round(_mean([r["recall_at_k"] for r in rows]), 6),
            "ndcg_at_k": round(_mean([r["ndcg_at_k"] for r in rows]), 6),
            "mrr": round(_mean([r["mrr"] for r in rows]), 6),
        }
    summary["latency_ms"] = {
        mode: _latency_summary(samples)
        for mode, samples in latency_ms.items()
    }

    return {"summary": summary, "per_query": per_query}


def _compare_and_gate(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    mode: str,
    tolerance: float,
    metric_drop_thresholds: dict[str, float] | None = None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    current_modes = (current.get("summary") or {}).get("modes") or {}
    baseline_modes = (baseline.get("summary") or baseline.get("modes") or {}).get("modes") or baseline.get("modes") or {}

    current_row = current_modes.get(mode) or {}
    baseline_row = baseline_modes.get(mode) or {}
    if not current_row or not baseline_row:
        failures.append(f"Missing mode={mode} in current/baseline results.")
        return False, failures

    thresholds = metric_drop_thresholds or {}
    for metric in ("precision_at_k", "recall_at_k", "ndcg_at_k", "mrr"):
        cur = float(current_row.get(metric, 0.0))
        base = float(baseline_row.get(metric, 0.0))
        allowed_drop = float(thresholds.get(metric, tolerance))
        delta = cur - base
        if delta < -allowed_drop:
            failures.append(
                f"{mode}.{metric} regression exceeded threshold: "
                f"delta={delta:+.6f}, allowed_drop={allowed_drop:.6f}, current={cur:.6f}, baseline={base:.6f}"
            )

    return len(failures) == 0, failures


def _metric_deltas(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    mode: str,
) -> dict[str, float]:
    current_modes = (current.get("summary") or {}).get("modes") or {}
    baseline_modes = (baseline.get("summary") or baseline.get("modes") or {}).get("modes") or baseline.get("modes") or {}

    current_row = current_modes.get(mode) or {}
    baseline_row = baseline_modes.get(mode) or {}
    if not current_row or not baseline_row:
        return {}

    deltas: dict[str, float] = {}
    for metric in ("precision_at_k", "recall_at_k", "ndcg_at_k", "mrr"):
        deltas[metric] = float(current_row.get(metric, 0.0)) - float(baseline_row.get(metric, 0.0))
    return deltas


def _gate_latency(
    *,
    current: dict[str, Any],
    mode: str,
    p95_budget_ms: float | None,
    mean_budget_ms: float | None,
    max_budget_ms: float | None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    latencies = ((current.get("summary") or {}).get("latency_ms") or {}).get(mode) or {}

    if not latencies:
        failures.append(f"Missing latency summary for mode={mode}.")
        return False, failures

    p95_value = float(latencies.get("p95", 0.0))
    mean_value = float(latencies.get("mean", 0.0))
    max_value = float(latencies.get("max", 0.0))

    if p95_budget_ms is not None and p95_value > float(p95_budget_ms):
        failures.append(f"{mode}.latency.p95 exceeded budget: {p95_value:.3f}ms > {float(p95_budget_ms):.3f}ms")
    if mean_budget_ms is not None and mean_value > float(mean_budget_ms):
        failures.append(f"{mode}.latency.mean exceeded budget: {mean_value:.3f}ms > {float(mean_budget_ms):.3f}ms")
    if max_budget_ms is not None and max_value > float(max_budget_ms):
        failures.append(f"{mode}.latency.max exceeded budget: {max_value:.3f}ms > {float(max_budget_ms):.3f}ms")

    return len(failures) == 0, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline retrieval benchmark (gold queries -> relevant ids).")
    parser.add_argument("--opportunities", type=str, default=str(_default_path("backend/benchmarks/data/opportunities.jsonl")))
    parser.add_argument("--gold", type=str, default=str(_default_path("backend/benchmarks/data/gold.jsonl")))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", type=str, default=str(_default_path("backend/benchmarks/results.json")))
    parser.add_argument("--baseline", type=str, default=str(_default_path("backend/benchmarks/baseline.json")))
    parser.add_argument("--write-baseline", action="store_true", help="Overwrite baseline.json with current summary.")
    parser.add_argument("--gate", action="store_true", help="Fail if semantic metrics regress vs baseline.")
    parser.add_argument("--tolerance", type=float, default=0.0, help="Allowed absolute drop vs baseline.")
    parser.add_argument(
        "--semantic-max-precision-drop",
        type=float,
        default=None,
        help="Allowed absolute drop vs baseline for semantic precision@k. Falls back to --tolerance.",
    )
    parser.add_argument(
        "--semantic-max-recall-drop",
        type=float,
        default=None,
        help="Allowed absolute drop vs baseline for semantic recall@k. Falls back to --tolerance.",
    )
    parser.add_argument(
        "--semantic-max-ndcg-drop",
        type=float,
        default=None,
        help="Allowed absolute drop vs baseline for semantic ndcg@k. Falls back to --tolerance.",
    )
    parser.add_argument(
        "--semantic-max-mrr-drop",
        type=float,
        default=None,
        help="Allowed absolute drop vs baseline for semantic MRR. Falls back to --tolerance.",
    )
    parser.add_argument("--semantic-p95-ms-budget", type=float, default=None, help="Fail if semantic latency p95 exceeds this budget.")
    parser.add_argument("--semantic-mean-ms-budget", type=float, default=None, help="Fail if semantic latency mean exceeds this budget.")
    parser.add_argument("--semantic-max-ms-budget", type=float, default=None, help="Fail if semantic latency max exceeds this budget.")
    args = parser.parse_args()

    opp_path = Path(args.opportunities)
    gold_path = Path(args.gold)
    out_path = Path(args.out)
    baseline_path = Path(args.baseline)

    opportunities = load_opportunities(opp_path)
    gold = load_gold(gold_path)

    current = asyncio.run(_run(opportunities=opportunities, gold=gold, k=args.k))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_only = {"summary": current["summary"]}
    if args.write_baseline:
        baseline_path.write_text(json.dumps(summary_only, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote baseline: {baseline_path}")
        print(json.dumps(summary_only["summary"], indent=2, sort_keys=True))
        return 0

    if args.gate:
        if not baseline_path.exists():
            print(f"Baseline file missing: {baseline_path}", file=sys.stderr)
            return 2
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        deltas = _metric_deltas(current=current, baseline=baseline, mode="semantic")
        if deltas:
            print("Semantic metric deltas vs baseline:")
            for metric in ("precision_at_k", "recall_at_k", "ndcg_at_k", "mrr"):
                if metric in deltas:
                    print(f"  {metric}: {deltas[metric]:+.6f}")
        metric_thresholds: dict[str, float] = {}
        if args.semantic_max_precision_drop is not None:
            metric_thresholds["precision_at_k"] = float(args.semantic_max_precision_drop)
        if args.semantic_max_recall_drop is not None:
            metric_thresholds["recall_at_k"] = float(args.semantic_max_recall_drop)
        if args.semantic_max_ndcg_drop is not None:
            metric_thresholds["ndcg_at_k"] = float(args.semantic_max_ndcg_drop)
        if args.semantic_max_mrr_drop is not None:
            metric_thresholds["mrr"] = float(args.semantic_max_mrr_drop)
        ok, failures = _compare_and_gate(
            current=current,
            baseline=baseline,
            mode="semantic",
            tolerance=float(args.tolerance),
            metric_drop_thresholds=metric_thresholds or None,
        )
        if not ok:
            for line in failures:
                print(line, file=sys.stderr)
            print("Current summary:", file=sys.stderr)
            print(json.dumps(current["summary"], indent=2, sort_keys=True), file=sys.stderr)
            return 3
        ok, failures = _gate_latency(
            current=current,
            mode="semantic",
            p95_budget_ms=args.semantic_p95_ms_budget,
            mean_budget_ms=args.semantic_mean_ms_budget,
            max_budget_ms=args.semantic_max_ms_budget,
        )
        if not ok:
            for line in failures:
                print(line, file=sys.stderr)
            print("Current summary:", file=sys.stderr)
            print(json.dumps(current["summary"], indent=2, sort_keys=True), file=sys.stderr)
            return 4

    print(json.dumps(current["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
