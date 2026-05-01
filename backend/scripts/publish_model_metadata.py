from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

MARKER_START = "<!-- MODEL_VERSION_METADATA:START -->"
MARKER_END = "<!-- MODEL_VERSION_METADATA:END -->"


def _client_kwargs() -> dict[str, Any]:
    import certifi

    from app.core.config import settings

    kwargs: dict[str, Any] = {}
    url = (settings.MONGODB_URL or "").strip().lower()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url
    )
    if tls_needed:
        kwargs.update(
            {
                "tls": True,
                "tlsCAFile": certifi.where(),
                "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
            }
        )
    return kwargs


def _format_float(value: Any, digits: int = 6) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


def _short_id(value: str | None) -> str:
    if not value:
        return "n/a"
    return value[:8]


async def _collect_snapshot(max_models: int) -> dict[str, Any]:
    import certifi
    from beanie import init_beanie
    from motor.motor_asyncio import AsyncIOMotorClient
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.core.config import settings
    from app.models.model_drift_report import ModelDriftReport
    from app.models.ranking_model_version import RankingModelVersion
    from app.core.time import utc_now

    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[RankingModelVersion, ModelDriftReport],
    )

    models = await RankingModelVersion.find_many().sort("-created_at").limit(max(1, int(max_models))).to_list()
    active = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
    drift = await ModelDriftReport.find_many().sort("-created_at").limit(1).to_list()
    latest_drift = drift[0] if drift else None

    snapshot = {
        "generated_at": utc_now().isoformat(),
        "policy": {
            "mode": settings.MLOPS_ACTIVATION_POLICY,
            "auto_activate": bool(settings.MLOPS_AUTO_ACTIVATE),
            "min_auc_gain": float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN),
            "min_positive_rate": float(settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE),
            "max_weight_shift": float(settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT),
            "retrain_interval_hours": int(settings.MLOPS_RETRAIN_INTERVAL_HOURS),
            "drift_check_interval_hours": int(settings.MLOPS_DRIFT_CHECK_INTERVAL_HOURS),
            "drift_retrain_on_alert": bool(settings.MLOPS_TRIGGER_RETRAIN_ON_DRIFT_ALERT),
            "alerts_enabled": bool(settings.MLOPS_ALERTS_ENABLED),
            "alert_cooldown_minutes": int(settings.MLOPS_ALERT_COOLDOWN_MINUTES),
        },
        "active_model": None,
        "recent_models": [],
        "latest_drift": None,
    }

    if active is not None:
        snapshot["active_model"] = {
            "id": str(active.id),
            "name": active.name,
            "created_at": active.created_at.isoformat(),
            "training_rows": int(active.training_rows or 0),
            "weights": {str(k): float(v) for k, v in (active.weights or {}).items()},
            "metrics": {str(k): float(v) for k, v in (active.metrics or {}).items()},
            "lifecycle": dict(active.lifecycle or {}),
            "notes": active.notes,
        }

    for model in models:
        snapshot["recent_models"].append(
            {
                "id": str(model.id),
                "name": model.name,
                "is_active": bool(model.is_active),
                "created_at": model.created_at.isoformat(),
                "training_rows": int(model.training_rows or 0),
                "metrics": {str(k): float(v) for k, v in (model.metrics or {}).items()},
                "lifecycle": dict(model.lifecycle or {}),
                "notes": model.notes,
            }
        )

    if latest_drift is not None:
        snapshot["latest_drift"] = {
            "id": str(latest_drift.id),
            "model_version_id": latest_drift.model_version_id,
            "created_at": latest_drift.created_at.isoformat(),
            "alert": bool(latest_drift.alert),
            "alert_notified_at": latest_drift.alert_notified_at.isoformat() if latest_drift.alert_notified_at else None,
            "metrics": latest_drift.metrics or {},
        }

    client.close()
    return snapshot


def _build_metadata_markdown(snapshot: dict[str, Any]) -> str:
    generated_at = str(snapshot.get("generated_at") or "n/a")
    policy = snapshot.get("policy") or {}
    active = snapshot.get("active_model") or {}
    recent = snapshot.get("recent_models") or []
    drift = snapshot.get("latest_drift") or {}

    lines: list[str] = []
    lines.append(f"Updated: **{generated_at}**")
    lines.append("")
    lines.append(
        "Policy: "
        f"`{policy.get('mode', 'n/a')}` "
        f"(auto_activate={policy.get('auto_activate', False)}, "
        f"min_auc_gain={policy.get('min_auc_gain', 'n/a')}, "
        f"min_positive_rate={policy.get('min_positive_rate', 'n/a')}, "
        f"max_weight_shift={policy.get('max_weight_shift', 'n/a')})"
    )
    lines.append(
        "Schedule: "
        f"retrain every `{policy.get('retrain_interval_hours', 'n/a')}h`, "
        f"drift check every `{policy.get('drift_check_interval_hours', 'n/a')}h`, "
        f"drift-triggered retrain=`{policy.get('drift_retrain_on_alert', False)}`"
    )
    lines.append(
        "Alerts: "
        f"enabled=`{policy.get('alerts_enabled', False)}`, "
        f"cooldown=`{policy.get('alert_cooldown_minutes', 'n/a')}m`"
    )
    lines.append("")

    if active:
        active_lifecycle = active.get("lifecycle") or {}
        active_metrics = active.get("metrics") or {}
        lines.append(
            "Active model: "
            f"`{_short_id(active.get('id'))}` ({active.get('name', 'n/a')}) "
            f"rows={active.get('training_rows', 0)} "
            f"auc_gain={_format_float(active_metrics.get('auc_gain'), 6)} "
            f"activation_reason=`{active_lifecycle.get('activation_reason', 'n/a')}`"
        )
    else:
        lines.append("Active model: `n/a`")

    lines.append("")
    lines.append("Recent model versions:")
    lines.append("")
    lines.append("| id | created_at | active | rows | auc_default | auc_learned | auc_gain | positive_rate | activation_reason |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")

    if recent:
        for model in recent:
            metrics = model.get("metrics") or {}
            lifecycle = model.get("lifecycle") or {}
            lines.append(
                "| "
                f"`{_short_id(model.get('id'))}` | "
                f"{model.get('created_at', 'n/a')} | "
                f"{'yes' if model.get('is_active') else 'no'} | "
                f"{int(model.get('training_rows') or 0)} | "
                f"{_format_float(metrics.get('auc_default'), 6)} | "
                f"{_format_float(metrics.get('auc_learned'), 6)} | "
                f"{_format_float(metrics.get('auc_gain'), 6)} | "
                f"{_format_float(metrics.get('positive_rate'), 6)} | "
                f"{lifecycle.get('activation_reason', 'n/a')} |"
            )
    else:
        lines.append("| `n/a` | n/a | no | 0 | n/a | n/a | n/a | n/a | n/a |")

    lines.append("")
    if drift:
        drift_metrics = drift.get("metrics") or {}
        lines.append(
            "Latest drift report: "
            f"id=`{_short_id(drift.get('id'))}` "
            f"alert=`{bool(drift.get('alert'))}` "
            f"psi={_format_float(drift_metrics.get('query_bucket_psi'), 6)} "
            f"max_z={_format_float(drift_metrics.get('max_feature_mean_z'), 6)} "
            f"notified_at={drift.get('alert_notified_at') or 'n/a'}"
        )
    else:
        lines.append("Latest drift report: `n/a`")

    return "\n".join(lines).strip()


def _upsert_readme_section(*, readme_path: Path, markdown: str) -> bool:
    content = readme_path.read_text(encoding="utf-8")
    if MARKER_START not in content or MARKER_END not in content:
        return False

    start = content.index(MARKER_START) + len(MARKER_START)
    end = content.index(MARKER_END)
    updated = content[:start] + "\n\n" + markdown + "\n\n" + content[end:]
    readme_path.write_text(updated, encoding="utf-8")
    return True


def _load_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


async def _main_async(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact)
    readme_path = Path(args.readme)

    snapshot: dict[str, Any]
    if args.from_artifact:
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_path}")
        snapshot = _load_artifact(artifact_path)
    else:
        try:
            snapshot = await _collect_snapshot(max_models=int(args.max_models))
            _save_artifact(artifact_path, snapshot)
        except Exception as exc:
            if not artifact_path.exists():
                raise RuntimeError(f"Failed to collect model metadata and no artifact fallback found: {exc}") from exc
            print(f"[publish_model_metadata] DB snapshot failed, using existing artifact: {exc}")
            snapshot = _load_artifact(artifact_path)

    markdown = _build_metadata_markdown(snapshot)
    ok = _upsert_readme_section(readme_path=readme_path, markdown=markdown)
    if not ok:
        raise RuntimeError(
            f"README section markers missing. Add {MARKER_START} ... {MARKER_END} to {readme_path}."
        )

    print(f"Updated README metadata section from {'artifact' if args.from_artifact else 'snapshot/artifact fallback'}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish ranking model lifecycle metadata into README.")
    parser.add_argument(
        "--readme",
        default=str(REPO_ROOT / "README.md"),
        help="Path to README file that contains model metadata markers.",
    )
    parser.add_argument(
        "--artifact",
        default=str(BACKEND_ROOT / "benchmarks" / "model_lifecycle_latest.json"),
        help="Path to metadata artifact JSON.",
    )
    parser.add_argument("--max-models", type=int, default=5)
    parser.add_argument(
        "--from-artifact",
        action="store_true",
        help="Skip DB reads and publish README metadata from the artifact JSON only.",
    )
    args = parser.parse_args()

    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
