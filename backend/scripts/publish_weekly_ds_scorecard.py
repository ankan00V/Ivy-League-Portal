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
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import analytics_bi_tool_url, settings
from app.core.time import utc_now
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.feature_store_row import FeatureStoreRow
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.data_science_observability_service import data_science_observability_service


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _render_markdown(payload: dict[str, Any]) -> str:
    snapshot = dict(payload.get("snapshot") or {})
    freshness = dict(snapshot.get("feature_freshness") or {})
    assistant = dict(snapshot.get("assistant_quality") or {})
    parity = dict(snapshot.get("parity") or {})
    drift = list(snapshot.get("drift") or [])
    latest_drift = drift[0] if drift else {}
    latest_drift_metrics = dict(latest_drift.get("metrics") or {})
    promotions = list(snapshot.get("model_promotions") or [])
    lines = [
        "# Weekly Data Science Operating Scorecard",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window (days): **{payload.get('window_days')}**",
        f"- Grafana Dashboard: **{payload.get('dashboard_url') or 'n/a'}**",
        f"- Dashboard Snapshot: **{payload.get('dashboard_snapshot_path') or 'n/a'}**",
        "",
        "## Gates And Health",
        "",
        f"- Feature freshness seconds: **{_fmt(freshness.get('freshness_seconds'))}**",
        f"- Latest drift alert: **{bool(latest_drift.get('alert')) if latest_drift else 'n/a'}**",
        f"- Latest PSI: **{_fmt(latest_drift_metrics.get('query_bucket_psi'))}**",
        f"- Latest max feature Z: **{_fmt(latest_drift_metrics.get('max_feature_mean_z'))}**",
        f"- Assistant failure rate: **{_fmt(assistant.get('failure_rate'))}**",
        f"- Assistant hallucination rate: **{_fmt(assistant.get('hallucination_rate'))}**",
        f"- Assistant citation correctness: **{_fmt(assistant.get('citation_correctness'))}**",
        "",
        "## Parity",
        "",
    ]
    for mode, row in sorted(dict(parity.get("online") or {}).items()):
        lines.append(
            f"- `{mode}` impressions={int(row.get('impressions') or 0)} "
            f"ctr={_fmt(row.get('ctr'))} apply_rate={_fmt(row.get('apply_rate'))}"
        )
    lines.extend(["", "## Model Promotion History", ""])
    for row in promotions[:10]:
        lines.append(
            f"- `{row.get('status')}` {row.get('name')} `{row.get('id')}` "
            f"auc_gain={_fmt(row.get('auc_gain'))} serving_ready={row.get('serving_ready')} "
            f"reason={row.get('activation_reason') or 'n/a'}"
        )
    if not promotions:
        lines.append("- n/a")
    lines.append("")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Persist DS dashboard snapshot data into a weekly scorecard.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dashboard-url", type=str, default=analytics_bi_tool_url() or "")
    parser.add_argument("--dashboard-snapshot-path", type=str, default="")
    parser.add_argument("--markdown-out", type=str, default="docs/portfolio/weekly_ds_scorecard.md")
    parser.add_argument("--json-out", type=str, default="backend/benchmarks/weekly_ds_scorecard.json")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            AssistantAuditEvent,
            FeatureStoreRow,
            ModelDriftReport,
            Opportunity,
            OpportunityInteraction,
            Profile,
            RankingModelVersion,
            RankingRequestTelemetry,
        ],
    )
    try:
        snapshot = await data_science_observability_service.operating_loop_snapshot(lookback_days=max(1, min(int(args.days), 90)))
        payload = {
            "generated_at": utc_now().isoformat(),
            "window_days": int(args.days),
            "dashboard_url": args.dashboard_url or None,
            "dashboard_snapshot_path": args.dashboard_snapshot_path or None,
            "snapshot": snapshot,
        }
        markdown = _render_markdown(payload)
        markdown_path = Path(args.markdown_out)
        json_path = Path(args.json_out)
        if not markdown_path.is_absolute():
            markdown_path = REPO_ROOT / markdown_path
        if not json_path.is_absolute():
            json_path = REPO_ROOT / json_path
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "markdown": str(markdown_path), "json": str(json_path)}, indent=2))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
