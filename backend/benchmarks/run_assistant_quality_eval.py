from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.services.assistant_service import assistant_service


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            raise ValueError(f"Invalid JSONL at {path}:{lineno}: {exc}") from exc
    return rows


def _evaluate(rows: list[dict[str, Any]], *, prompt_version: str) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    route_matches = 0
    tool_matches = 0
    expected_tool_rows = 0
    for row in rows:
        route, tool = assistant_service._tool_route(str(row.get("input") or ""))
        expected_mode = str(row.get("expected_mode") or "").strip()
        expected_tool = row.get("expected_tool")
        route_ok = route == expected_mode
        tool_ok = expected_tool is None or tool == expected_tool
        route_matches += 1 if route_ok else 0
        if expected_tool is not None:
            expected_tool_rows += 1
            tool_matches += 1 if tool_ok else 0
        details.append(
            {
                "category": row.get("category") or "legacy",
                "input": row.get("input"),
                "expected_mode": expected_mode,
                "actual_mode": route,
                "expected_tool": expected_tool,
                "actual_tool": tool,
                "route_ok": route_ok,
                "tool_ok": tool_ok,
                "quality_checks": row.get("quality_checks") or [],
            }
        )
    total = len(rows)
    route_precision = route_matches / float(max(1, total))
    tool_precision = tool_matches / float(max(1, expected_tool_rows))
    return {
        "generated_at": utc_now().isoformat(),
        "prompt_version": prompt_version,
        "dataset_size": total,
        "metrics": {
            "tool_route_precision": round(route_precision, 6),
            "expected_tool_precision": round(tool_precision, 6),
            "hallucination_rate": None,
            "citation_correctness": None,
            "latency_p95_ms": None,
            "user_feedback_positive_rate": None,
        },
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run assistant golden eval route/prompt-version checks.")
    parser.add_argument("--dataset", type=str, default="backend/benchmarks/data/assistant_general_eval.jsonl")
    parser.add_argument("--prompt-version", type=str, default=settings.ASSISTANT_CHAT_PROMPT_VERSION)
    parser.add_argument("--compare-prompt-version", type=str, default="")
    parser.add_argument("--min-route-precision", type=float, default=0.85)
    parser.add_argument("--out", type=str, default="backend/benchmarks/assistant_quality_eval.json")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = REPO_ROOT / dataset_path
    rows = _load_jsonl(dataset_path)
    current = _evaluate(rows, prompt_version=args.prompt_version)
    payload: dict[str, Any] = {"current": current}
    if args.compare_prompt_version:
        payload["comparison"] = {
            "candidate": current,
            "baseline_prompt_version": args.compare_prompt_version,
            "required_manual_judge": True,
            "notes": "Route checks are deterministic; run LLM judge/human review for hallucination and citation correctness before prompt promotion.",
        }

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "metrics": current["metrics"], "out": str(out_path)}, indent=2))

    if args.fail_on_regression and float(current["metrics"]["tool_route_precision"]) < float(args.min_route_precision):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
