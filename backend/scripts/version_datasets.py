from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
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
from app.models.feature_store_row import FeatureStoreRow
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry


def _stable_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _hash_identity(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:20]


def _sanitize_row(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"Unsupported row type: {type(value)!r}")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_stable_json(row))
            handle.write("\n")


async def _snapshot(args: argparse.Namespace) -> dict[str, Any]:
    lookback_days = max(1, min(int(args.lookback_days), 3650))
    since = datetime.utcnow() - timedelta(days=lookback_days)
    generated_at = datetime.utcnow()

    dataset_tag = (args.name or "snapshot").strip().lower().replace(" ", "-")
    timestamp = generated_at.strftime("%Y%m%d-%H%M%S")
    version_id = f"{timestamp}-{dataset_tag}"
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    output_dir = output_root / version_id
    output_dir.mkdir(parents=True, exist_ok=True)

    user_salt = hashlib.sha256(f"{version_id}:{settings.SECRET_KEY}".encode("utf-8")).hexdigest()[:16]

    opportunities = await Opportunity.find_many().sort("-last_seen_at").to_list()
    interactions = await OpportunityInteraction.find_many(
        OpportunityInteraction.created_at >= since
    ).sort("-created_at").to_list()
    telemetry = await RankingRequestTelemetry.find_many(
        RankingRequestTelemetry.created_at >= since
    ).sort("-created_at").to_list()
    feature_rows = await FeatureStoreRow.find_many(
        FeatureStoreRow.date >= since.strftime("%Y-%m-%d")
    ).sort("-date").to_list()

    opportunity_rows = [_sanitize_row(item) for item in opportunities]

    interaction_rows: list[dict[str, Any]] = []
    for item in interactions:
        row = _sanitize_row(item)
        if row.get("user_id"):
            row["user_id"] = _hash_identity(str(row["user_id"]), user_salt)
        interaction_rows.append(row)

    telemetry_rows: list[dict[str, Any]] = []
    for item in telemetry:
        row = _sanitize_row(item)
        if row.get("user_id"):
            row["user_id"] = _hash_identity(str(row["user_id"]), user_salt)
        telemetry_rows.append(row)

    feature_store_rows: list[dict[str, Any]] = []
    for item in feature_rows:
        row = _sanitize_row(item)
        if row.get("user_id"):
            row["user_id"] = _hash_identity(str(row["user_id"]), user_salt)
        feature_store_rows.append(row)

    files: list[tuple[str, list[dict[str, Any]]]] = [
        ("opportunities.jsonl", opportunity_rows),
        ("interactions.jsonl", interaction_rows),
        ("ranking_request_telemetry.jsonl", telemetry_rows),
        ("feature_store_rows.jsonl", feature_store_rows),
    ]

    file_meta: list[dict[str, Any]] = []
    for filename, rows in files:
        path = output_dir / filename
        _write_jsonl(path, rows)
        file_meta.append(
            {
                "file": filename,
                "rows": len(rows),
                "sha256": _sha256_file(path),
            }
        )

    manifest = {
        "dataset_version": version_id,
        "generated_at": generated_at.isoformat(),
        "lookback_days": lookback_days,
        "window_start": since.isoformat(),
        "window_end": generated_at.isoformat(),
        "mongodb_database": settings.MONGODB_DB_NAME,
        "anonymized_user_ids": True,
        "files": file_meta,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "status": "ok",
        "dataset_version": version_id,
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
        "files": file_meta,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a versioned analytics/ML dataset snapshot from MongoDB with anonymized user IDs."
    )
    parser.add_argument("--name", type=str, default="snapshot", help="Human-friendly dataset tag.")
    parser.add_argument("--lookback-days", type=int, default=180, help="Rolling lookback window for event snapshots.")
    parser.add_argument(
        "--output-root",
        type=str,
        default="backend/benchmarks/datasets",
        help="Output root directory (a version folder is created underneath).",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[Opportunity, OpportunityInteraction, RankingRequestTelemetry, FeatureStoreRow],
    )
    try:
        payload = await _snapshot(args)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
