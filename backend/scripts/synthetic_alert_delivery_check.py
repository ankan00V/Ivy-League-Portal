from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now


def _post_json(*, url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text
    return {
        "status_code": response.status_code,
        "body": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a synthetic Slack + PagerDuty alert and acknowledge it.")
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/synthetic_alert_delivery.json",
    )
    args = parser.parse_args()

    slack_webhook_url = str(settings.MLOPS_ALERT_SLACK_WEBHOOK_URL or "").strip()
    pagerduty_routing_key = str(settings.MLOPS_ALERT_PAGERDUTY_ROUTING_KEY or "").strip()
    timeout = max(1.0, float(settings.MLOPS_ALERT_WEBHOOK_TIMEOUT_SECONDS))
    if not slack_webhook_url:
        raise RuntimeError("MLOPS_ALERT_SLACK_WEBHOOK_URL is required for synthetic alert delivery checks.")
    if not pagerduty_routing_key:
        raise RuntimeError("MLOPS_ALERT_PAGERDUTY_ROUTING_KEY is required for synthetic alert delivery checks.")

    test_id = f"synthetic-{uuid.uuid4().hex[:12]}"
    occurred_at = utc_now().isoformat()

    slack_payload = {
        "text": f"VidyaVerse synthetic alert delivery check `{test_id}`",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*VidyaVerse synthetic alert delivery check*\n`{test_id}` at `{occurred_at}`",
                },
            }
        ],
    }
    pagerduty_base = {
        "routing_key": pagerduty_routing_key,
        "dedup_key": test_id,
        "payload": {
            "summary": f"VidyaVerse synthetic alert delivery check {test_id}",
            "source": "vidyaverse-ops-synthetic",
            "severity": "info",
            "timestamp": occurred_at,
            "component": "ops",
            "group": "synthetic",
            "class": "alert_delivery_check",
            "custom_details": {
                "check": "synthetic_alert_delivery",
                "test_id": test_id,
                "occurred_at": occurred_at,
            },
        },
    }

    result = {
        "generated_at": occurred_at,
        "test_id": test_id,
        "slack": _post_json(url=slack_webhook_url, payload=slack_payload, timeout=timeout),
        "pagerduty": {
            "trigger": _post_json(
                url="https://events.pagerduty.com/v2/enqueue",
                payload={**pagerduty_base, "event_action": "trigger"},
                timeout=timeout,
            ),
            "acknowledge": _post_json(
                url="https://events.pagerduty.com/v2/enqueue",
                payload={**pagerduty_base, "event_action": "acknowledge"},
                timeout=timeout,
            ),
            "resolve": _post_json(
                url="https://events.pagerduty.com/v2/enqueue",
                payload={**pagerduty_base, "event_action": "resolve"},
                timeout=timeout,
            ),
        },
    }

    json_path = Path(args.json_out)
    if not json_path.is_absolute():
        json_path = REPO_ROOT / json_path
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({"status": "ok", "artifact": str(json_path), "test_id": test_id}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
