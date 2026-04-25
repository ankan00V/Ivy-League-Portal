from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.application import Application
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry


def _safe_float(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _is_real_traffic(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"", "real"}


def _window_label(start: datetime, end: datetime) -> str:
    return f"{start.date().isoformat()}->{end.date().isoformat()}"


def _extract_user_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def _window_metrics(*, start: datetime, end: datetime) -> dict[str, Any]:
    interactions = await OpportunityInteraction.find_many(
        OpportunityInteraction.created_at >= start,
        OpportunityInteraction.created_at < end,
    ).to_list()
    interactions = [row for row in interactions if _is_real_traffic(getattr(row, "traffic_type", None))]

    telemetry = await RankingRequestTelemetry.find_many(
        RankingRequestTelemetry.created_at >= start,
        RankingRequestTelemetry.created_at < end,
    ).to_list()
    telemetry = [row for row in telemetry if _is_real_traffic(getattr(row, "traffic_type", None))]

    applications = await Application.find_many(
        Application.created_at >= start,
        Application.created_at < end,
    ).to_list()

    active_users: set[str] = set()
    for row in interactions:
        user_id = _extract_user_id(getattr(row, "user_id", None))
        if user_id:
            active_users.add(user_id)
    for row in telemetry:
        user_id = _extract_user_id(getattr(row, "user_id", None))
        if user_id:
            active_users.add(user_id)

    by_mode_counts: dict[str, Counter] = defaultdict(Counter)
    interaction_counter = Counter()
    for row in interactions:
        mode = str(getattr(row, "ranking_mode", None) or "unknown")
        interaction_type = str(getattr(row, "interaction_type", "") or "").strip().lower() or "unknown"
        interaction_counter[interaction_type] += 1
        by_mode_counts[mode][interaction_type] += 1

    mode_request_counter = Counter(str(getattr(row, "ranking_mode", None) or "unknown") for row in telemetry)
    mode_failure_counter = Counter(
        str(getattr(row, "ranking_mode", None) or "unknown")
        for row in telemetry
        if not bool(getattr(row, "success", True))
    )

    def _ctr(clicks: int, impressions: int) -> float:
        return _safe_float((clicks / impressions) if impressions > 0 else 0.0)

    impressions = _safe_int(interaction_counter.get("impression"))
    clicks = _safe_int(interaction_counter.get("click"))
    applies = _safe_int(interaction_counter.get("apply"))
    applications_created = len(applications)
    requests_total = len(telemetry)
    requests_failed = sum(1 for row in telemetry if not bool(getattr(row, "success", True)))

    per_mode: dict[str, Any] = {}
    for mode in sorted(set(by_mode_counts.keys()) | set(mode_request_counter.keys())):
        mode_impressions = _safe_int(by_mode_counts[mode].get("impression"))
        mode_clicks = _safe_int(by_mode_counts[mode].get("click"))
        mode_applies = _safe_int(by_mode_counts[mode].get("apply"))
        mode_requests = _safe_int(mode_request_counter.get(mode))
        mode_failures = _safe_int(mode_failure_counter.get(mode))
        per_mode[mode] = {
            "impressions": mode_impressions,
            "clicks": mode_clicks,
            "applies": mode_applies,
            "ctr": _ctr(mode_clicks, mode_impressions),
            "apply_rate": _ctr(mode_applies, mode_impressions),
            "requests": mode_requests,
            "failure_rate": _safe_float((mode_failures / mode_requests) if mode_requests > 0 else 0.0),
        }

    return {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_label": _window_label(start, end),
        "active_users": len(active_users),
        "applications_created": applications_created,
        "impressions": impressions,
        "clicks": clicks,
        "applies": applies,
        "ctr": _ctr(clicks, impressions),
        "apply_rate": _ctr(applies, impressions),
        "requests": requests_total,
        "request_failure_rate": _safe_float((requests_failed / requests_total) if requests_total > 0 else 0.0),
        "per_mode": per_mode,
    }


def _delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> float:
    return _safe_float(_safe_float(current.get(key)) - _safe_float(previous.get(key)))


def _render_markdown(payload: dict[str, Any]) -> str:
    current = payload.get("current_window") or {}
    previous = payload.get("previous_window") or {}
    deltas = payload.get("deltas") or {}
    lines = [
        "# Weekly Business Impact Scorecard",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window days: **{payload.get('window_days')}**",
        "",
        "## Current Window",
        "",
        f"- Period: **{current.get('window_label')}**",
        f"- Active users: **{_safe_int(current.get('active_users')):,}**",
        f"- Applications created: **{_safe_int(current.get('applications_created')):,}**",
        f"- Impressions: **{_safe_int(current.get('impressions')):,}**",
        f"- Clicks: **{_safe_int(current.get('clicks')):,}**",
        f"- Applies: **{_safe_int(current.get('applies')):,}**",
        f"- CTR: **{_safe_float(current.get('ctr')):.6f}**",
        f"- Apply rate: **{_safe_float(current.get('apply_rate')):.6f}**",
        f"- Request failure rate: **{_safe_float(current.get('request_failure_rate')):.6f}**",
        "",
        "## Week-over-Week Delta",
        "",
        f"- Active users delta: **{_safe_float(deltas.get('active_users')):.6f}**",
        f"- Applications created delta: **{_safe_float(deltas.get('applications_created')):.6f}**",
        f"- CTR delta: **{_safe_float(deltas.get('ctr')):.6f}**",
        f"- Apply-rate delta: **{_safe_float(deltas.get('apply_rate')):.6f}**",
        f"- Failure-rate delta: **{_safe_float(deltas.get('request_failure_rate')):.6f}**",
        "",
        "## Mode Breakdown (Current Window)",
        "",
        "| Mode | Impressions | Clicks | Applies | CTR | Apply rate | Requests | Failure rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    per_mode = current.get("per_mode") or {}
    for mode in sorted(per_mode.keys()):
        row = per_mode.get(mode) or {}
        lines.append(
            "| "
            f"`{mode}` | "
            f"{_safe_int(row.get('impressions'))} | "
            f"{_safe_int(row.get('clicks'))} | "
            f"{_safe_int(row.get('applies'))} | "
            f"{_safe_float(row.get('ctr')):.6f} | "
            f"{_safe_float(row.get('apply_rate')):.6f} | "
            f"{_safe_int(row.get('requests'))} | "
            f"{_safe_float(row.get('failure_rate')):.6f} |"
        )
    lines.append("")
    lines.append("## Previous Window")
    lines.append("")
    lines.append(f"- Period: **{previous.get('window_label')}**")
    lines.append(f"- Active users: **{_safe_int(previous.get('active_users')):,}**")
    lines.append(f"- Applications created: **{_safe_int(previous.get('applications_created')):,}**")
    lines.append(f"- CTR: **{_safe_float(previous.get('ctr')):.6f}**")
    lines.append(f"- Apply rate: **{_safe_float(previous.get('apply_rate')):.6f}**")
    lines.append(f"- Request failure rate: **{_safe_float(previous.get('request_failure_rate')):.6f}**")
    lines.append("")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Publish weekly business-impact scorecard artifacts.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/weekly_business_impact_scorecard.json",
    )
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/weekly_business_impact_scorecard.md",
    )
    args = parser.parse_args()

    days = max(1, min(int(args.days), 30))
    now = datetime.utcnow()
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[OpportunityInteraction, RankingRequestTelemetry, Application],
    )
    try:
        current_window = await _window_metrics(start=current_start, end=now)
        previous_window = await _window_metrics(start=previous_start, end=current_start)
        deltas = {
            "active_users": _delta(current_window, previous_window, "active_users"),
            "applications_created": _delta(current_window, previous_window, "applications_created"),
            "ctr": _delta(current_window, previous_window, "ctr"),
            "apply_rate": _delta(current_window, previous_window, "apply_rate"),
            "request_failure_rate": _delta(current_window, previous_window, "request_failure_rate"),
        }
        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "window_days": days,
            "current_window": current_window,
            "previous_window": previous_window,
            "deltas": deltas,
        }

        json_path = Path(args.json_out)
        markdown_path = Path(args.markdown_out)
        if not json_path.is_absolute():
            json_path = REPO_ROOT / json_path
        if not markdown_path.is_absolute():
            markdown_path = REPO_ROOT / markdown_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)

        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "window_days": days,
                    "json": str(json_path),
                    "markdown": str(markdown_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
