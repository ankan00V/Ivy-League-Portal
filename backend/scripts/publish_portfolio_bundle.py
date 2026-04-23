#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

ABLATION_MARKER_START = "<!-- ABLATION_TABLE:START -->"
ABLATION_MARKER_END = "<!-- ABLATION_TABLE:END -->"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _metric(summary: dict[str, Any], mode: str, key: str) -> float | None:
    try:
        return float((((summary.get("modes") or {}).get(mode) or {}).get(key)))
    except Exception:
        return None


def _fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _gain(base: float | None, candidate: float | None) -> str:
    if base is None or candidate is None:
        return "n/a"
    if abs(base) < 1e-12:
        return "n/a"
    pct = ((candidate - base) / abs(base)) * 100.0
    return f"{pct:+.2f}%"


def _build_ablation_markdown(*, benchmark_summary: dict[str, Any], lifecycle: dict[str, Any]) -> str:
    profile = str(benchmark_summary.get("profile") or "n/a")
    query_count = int(benchmark_summary.get("query_count") or 0)
    k_value = int(benchmark_summary.get("k") or 0)
    temporal = benchmark_summary.get("temporal_holdout") or {}

    baseline_precision = _metric(benchmark_summary, "baseline", "precision_at_k")
    semantic_precision = _metric(benchmark_summary, "semantic", "precision_at_k")
    baseline_recall = _metric(benchmark_summary, "baseline", "recall_at_k")
    semantic_recall = _metric(benchmark_summary, "semantic", "recall_at_k")
    baseline_ndcg = _metric(benchmark_summary, "baseline", "ndcg_at_k")
    semantic_ndcg = _metric(benchmark_summary, "semantic", "ndcg_at_k")
    baseline_mrr = _metric(benchmark_summary, "baseline", "mrr")
    semantic_mrr = _metric(benchmark_summary, "semantic", "mrr")

    active = lifecycle.get("active_model") or {}
    active_metrics = active.get("metrics") or {}
    auc_default = active_metrics.get("auc_default")
    auc_learned = active_metrics.get("auc_learned")
    auc_gain = active_metrics.get("auc_gain")
    rows = active.get("training_rows")

    lines: list[str] = []
    lines.append(f"Benchmark profile: `{profile}`")
    lines.append(f"Temporal holdout enabled: `{bool(temporal.get('enabled', False))}`")
    lines.append(f"Queries: `{query_count}` at `K={k_value}`")
    lines.append("")
    lines.append("| Slice | Baseline | Candidate | Relative Gain |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| Precision@{k_value} | {_fmt(baseline_precision)} | {_fmt(semantic_precision)} | {_gain(baseline_precision, semantic_precision)} |"
    )
    lines.append(
        f"| Recall@{k_value} | {_fmt(baseline_recall)} | {_fmt(semantic_recall)} | {_gain(baseline_recall, semantic_recall)} |"
    )
    lines.append(
        f"| nDCG@{k_value} | {_fmt(baseline_ndcg)} | {_fmt(semantic_ndcg)} | {_gain(baseline_ndcg, semantic_ndcg)} |"
    )
    lines.append(
        f"| MRR@{k_value} | {_fmt(baseline_mrr)} | {_fmt(semantic_mrr)} | {_gain(baseline_mrr, semantic_mrr)} |"
    )
    lines.append(
        f"| Ranker AUC (validation/test) | {_fmt(float(auc_default) if auc_default is not None else None)} | {_fmt(float(auc_learned) if auc_learned is not None else None)} | {_gain(float(auc_default) if auc_default is not None else None, float(auc_learned) if auc_learned is not None else None)} |"
    )
    lines.append("")
    lines.append(
        "Active model snapshot: "
        f"id=`{str(active.get('id') or 'n/a')[:8]}` "
        f"rows=`{rows if rows is not None else 'n/a'}` "
        f"auc_gain=`{_fmt(float(auc_gain) if auc_gain is not None else None)}`"
    )
    return "\n".join(lines)


def _replace_marked_section(*, path: Path, start_marker: str, end_marker: str, replacement: str) -> None:
    content = path.read_text(encoding="utf-8")
    if start_marker not in content or end_marker not in content:
        raise RuntimeError(f"Markers missing in {path}: {start_marker} .. {end_marker}")
    start = content.index(start_marker) + len(start_marker)
    end = content.index(end_marker)
    updated = content[:start] + "\n" + replacement.strip() + "\n" + content[end:]
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish portfolio/ATS ablation markdown from benchmark artifacts.")
    parser.add_argument(
        "--benchmark",
        default=str(BACKEND_ROOT / "benchmarks" / "results.production_temporal_holdout.json"),
    )
    parser.add_argument(
        "--lifecycle",
        default=str(BACKEND_ROOT / "benchmarks" / "model_lifecycle_latest.json"),
    )
    parser.add_argument(
        "--ablation-md",
        default=str(REPO_ROOT / "docs" / "portfolio" / "ablation_table.md"),
    )
    args = parser.parse_args()

    benchmark = _read_json(Path(args.benchmark))
    lifecycle = _read_json(Path(args.lifecycle))
    benchmark_summary = benchmark.get("summary") or {}

    markdown = _build_ablation_markdown(
        benchmark_summary=benchmark_summary,
        lifecycle=lifecycle,
    )
    _replace_marked_section(
        path=Path(args.ablation_md),
        start_marker=ABLATION_MARKER_START,
        end_marker=ABLATION_MARKER_END,
        replacement=markdown,
    )
    print(f"Updated ablation bundle: {args.ablation_md}")


if __name__ == "__main__":
    main()
