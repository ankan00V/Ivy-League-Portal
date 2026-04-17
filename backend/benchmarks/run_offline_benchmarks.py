from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#]+")


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    embedding_provider: str
    opportunities_path: str
    gold_path: str
    holdout_after: str | None = None
    description: str = ""


@dataclass(frozen=True)
class OpportunityFixture:
    id: str
    title: str
    description: str
    domain: str | None = None
    opportunity_type: str | None = None
    university: str | None = None
    published_at: datetime | None = None

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
    split: str = "all"
    not_before: datetime | None = None


BENCHMARK_PROFILES: dict[str, BenchmarkProfile] = {
    "ci_hash": BenchmarkProfile(
        name="ci_hash",
        embedding_provider="hash",
        opportunities_path="backend/benchmarks/data/opportunities.jsonl",
        gold_path="backend/benchmarks/data/gold.jsonl",
        description="Deterministic CI gate with hash embeddings.",
    ),
    "production_temporal_holdout": BenchmarkProfile(
        name="production_temporal_holdout",
        embedding_provider="sentence_transformers",
        opportunities_path="backend/benchmarks/data/opportunities_temporal.jsonl",
        gold_path="backend/benchmarks/data/gold_temporal_holdout.jsonl",
        holdout_after="2025-01-01T00:00:00",
        description="Harder paraphrased queries evaluated on a temporal holdout with the production embedding path.",
    ),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_path(relative: str) -> Path:
    return _repo_root() / relative


def _default_output_path(profile_name: str, kind: str) -> Path:
    suffix = "" if profile_name == "ci_hash" else f".{profile_name}"
    filename = f"{kind}{suffix}.json"
    return _default_path(f"backend/benchmarks/{filename}")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


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
                published_at=_parse_datetime(row.get("published_at")),
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
        items.append(
            GoldQuery(
                query=query,
                relevant_ids=[str(value) for value in relevant if value],
                split=str(row.get("split") or "all"),
                not_before=_parse_datetime(row.get("not_before")),
            )
        )
    if not items:
        raise ValueError(f"No gold queries loaded from {path}")
    return items


def _apply_profile_filters(
    *,
    opportunities: list[OpportunityFixture],
    gold: list[GoldQuery],
    profile: BenchmarkProfile,
) -> tuple[list[OpportunityFixture], list[GoldQuery], dict[str, Any]]:
    if not profile.holdout_after:
        return opportunities, gold, {"enabled": False}

    cutoff = _parse_datetime(profile.holdout_after)
    if cutoff is None:
        raise ValueError(f"Invalid holdout_after for profile={profile.name}")

    filtered_opportunities = [
        opportunity
        for opportunity in opportunities
        if opportunity.published_at is None or opportunity.published_at >= cutoff
    ]
    holdout_ids = {opportunity.id for opportunity in filtered_opportunities}
    filtered_gold = [
        item
        for item in gold
        if (item.split == "holdout" or (item.not_before is not None and item.not_before >= cutoff))
        and any(relevant_id in holdout_ids for relevant_id in item.relevant_ids)
    ]

    return filtered_opportunities, filtered_gold, {
        "enabled": True,
        "cutoff": cutoff.isoformat(),
        "corpus_total": len(opportunities),
        "corpus_holdout": len(filtered_opportunities),
        "queries_total": len(gold),
        "queries_holdout": len(filtered_gold),
    }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) >= 2}


def _lexical_score(query: str, opportunity_text: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    o = _tokens(opportunity_text)
    if not o:
        return 0.0
    return float(len(q.intersection(o)))


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
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": round(sum(values_ms) / float(len(values_ms)), 6),
        "p50": round(_percentile(values_ms, 50.0), 6),
        "p95": round(_percentile(values_ms, 95.0), 6),
        "max": round(max(values_ms), 6),
    }


def _configure_environment(profile: BenchmarkProfile) -> None:
    os.environ["EMBEDDING_PROVIDER"] = profile.embedding_provider
    if profile.embedding_provider == "hash":
        os.environ.setdefault("OPENAI_API_KEY", "")


async def _run(
    *,
    profile: BenchmarkProfile,
    opportunities: list[OpportunityFixture],
    gold: list[GoldQuery],
    temporal_holdout: dict[str, Any],
    k: int,
) -> dict[str, Any]:
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

        t0 = time.perf_counter()
        baseline_scores = [_lexical_score(item.query, text) for text in opp_texts]
        baseline_ranked = _sort_ids_by_score(opp_ids, baseline_scores)
        latency_ms["baseline"].append((time.perf_counter() - t0) * 1000.0)

        t1 = time.perf_counter()
        q_vec = await embedding_service.embed_text(item.query)
        sim_scores = (opp_vectors @ q_vec).tolist()
        semantic_ranked = _sort_ids_by_score(opp_ids, [float(value) for value in sim_scores])
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
        "profile": profile.name,
        "description": profile.description,
        "embedding_provider": profile.embedding_provider,
        "embedding_runtime_provider": (
            "hash_fallback"
            if profile.embedding_provider in {"sentence_transformers", "auto"}
            and bool(getattr(embedding_service, "_local_model_disabled", False))
            else profile.embedding_provider
        ),
        "k": safe_k,
        "query_count": len(gold),
        "corpus_size": len(opportunities),
        "temporal_holdout": temporal_holdout,
        "modes": {},
    }
    for mode, rows in mode_metrics.items():
        summary["modes"][mode] = {
            "precision_at_k": round(_mean([row["precision_at_k"] for row in rows]), 6),
            "recall_at_k": round(_mean([row["recall_at_k"] for row in rows]), 6),
            "ndcg_at_k": round(_mean([row["ndcg_at_k"] for row in rows]), 6),
            "mrr": round(_mean([row["mrr"] for row in rows]), 6),
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
        current_value = float(current_row.get(metric, 0.0))
        baseline_value = float(baseline_row.get(metric, 0.0))
        allowed_drop = float(thresholds.get(metric, tolerance))
        delta = current_value - baseline_value
        if delta < -allowed_drop:
            failures.append(
                f"{mode}.{metric} regression exceeded threshold: "
                f"delta={delta:+.6f}, allowed_drop={allowed_drop:.6f}, current={current_value:.6f}, baseline={baseline_value:.6f}"
            )
    return len(failures) == 0, failures


def _metric_deltas(*, current: dict[str, Any], baseline: dict[str, Any], mode: str) -> dict[str, float]:
    current_modes = (current.get("summary") or {}).get("modes") or {}
    baseline_modes = (baseline.get("summary") or baseline.get("modes") or {}).get("modes") or baseline.get("modes") or {}
    current_row = current_modes.get(mode) or {}
    baseline_row = baseline_modes.get(mode) or {}
    if not current_row or not baseline_row:
        return {}
    return {
        metric: float(current_row.get(metric, 0.0)) - float(baseline_row.get(metric, 0.0))
        for metric in ("precision_at_k", "recall_at_k", "ndcg_at_k", "mrr")
    }


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
    parser.add_argument("--profile", choices=sorted(BENCHMARK_PROFILES.keys()), default="ci_hash")
    parser.add_argument("--opportunities", type=str, default=None)
    parser.add_argument("--gold", type=str, default=None)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--baseline", type=str, default=None)
    parser.add_argument("--write-baseline", action="store_true", help="Overwrite the profile baseline with current summary.")
    parser.add_argument("--gate", action="store_true", help="Fail if semantic metrics regress vs baseline.")
    parser.add_argument("--tolerance", type=float, default=0.0, help="Allowed absolute drop vs baseline.")
    parser.add_argument("--semantic-max-precision-drop", type=float, default=None)
    parser.add_argument("--semantic-max-recall-drop", type=float, default=None)
    parser.add_argument("--semantic-max-ndcg-drop", type=float, default=None)
    parser.add_argument("--semantic-max-mrr-drop", type=float, default=None)
    parser.add_argument("--semantic-p95-ms-budget", type=float, default=None)
    parser.add_argument("--semantic-mean-ms-budget", type=float, default=None)
    parser.add_argument("--semantic-max-ms-budget", type=float, default=None)
    args = parser.parse_args()

    profile = BENCHMARK_PROFILES[args.profile]
    _configure_environment(profile)

    opportunities_path = Path(args.opportunities) if args.opportunities else _default_path(profile.opportunities_path)
    gold_path = Path(args.gold) if args.gold else _default_path(profile.gold_path)
    out_path = Path(args.out) if args.out else _default_output_path(profile.name, "results")
    baseline_path = Path(args.baseline) if args.baseline else _default_output_path(profile.name == "ci_hash" and "ci_hash" or profile.name, "baseline")
    if profile.name == "ci_hash" and args.baseline is None:
        baseline_path = _default_path("backend/benchmarks/baseline.json")

    opportunities = load_opportunities(opportunities_path)
    gold = load_gold(gold_path)
    filtered_opportunities, filtered_gold, temporal_holdout = _apply_profile_filters(
        opportunities=opportunities,
        gold=gold,
        profile=profile,
    )
    if not filtered_opportunities:
        raise ValueError(f"profile={profile.name} yielded zero opportunities")
    if not filtered_gold:
        raise ValueError(f"profile={profile.name} yielded zero gold queries")

    current = asyncio.run(
        _run(
            profile=profile,
            opportunities=filtered_opportunities,
            gold=filtered_gold,
            temporal_holdout=temporal_holdout,
            k=args.k,
        )
    )
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
