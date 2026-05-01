from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.services.model_artifact_service import model_artifact_service


def _mongo_client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip().lower()
    if not (
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url
    ):
        return {}
    return {
        "tls": True,
        "tlsCAFile": certifi.where(),
        "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
    }


async def _mongo_drill(*, execute: bool, require_mongodump: bool) -> dict[str, Any]:
    if not execute:
        return {"name": "mongo_backup_restore", "ok": True, "skipped": True, "detail": "pass --execute to run the drill"}
    mongo_tools_available = bool(shutil.which("mongodump") and shutil.which("mongorestore"))
    if require_mongodump and not mongo_tools_available:
        return {
            "name": "mongo_backup_restore",
            "ok": False,
            "detail": "mongodump and mongorestore must be installed on the runner",
        }

    collection = "_backup_restore_drill"
    drill_id = f"drill-{utc_now().strftime('%Y%m%dT%H%M%S')}"
    client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=8000, **_mongo_client_kwargs())
    db = client[settings.MONGODB_DB_NAME]
    try:
        await db[collection].delete_many({})
        await db[collection].insert_one({"_id": drill_id, "created_at": utc_now().isoformat(), "purpose": "backup_restore_drill"})
        if not mongo_tools_available:
            rows = [row async for row in db[collection].find({})]
            await db[collection].delete_one({"_id": drill_id})
            if rows:
                await db[collection].insert_many(rows)
            restored = await db[collection].find_one({"_id": drill_id})
            ok = restored is not None
            return {
                "name": "mongo_backup_restore",
                "ok": ok,
                "detail": "temporary collection restored with logical fallback; install mongodump/mongorestore for archive drill",
                "collection": collection,
                "method": "logical_fallback",
            }
        with tempfile.TemporaryDirectory(prefix="vidyaverse-mongo-drill-") as tmpdir:
            archive = Path(tmpdir) / "mongo-drill.archive.gz"
            dump_cmd = [
                "mongodump",
                "--uri",
                settings.MONGODB_URL,
                "--db",
                settings.MONGODB_DB_NAME,
                "--collection",
                collection,
                "--archive=" + str(archive),
                "--gzip",
            ]
            restore_cmd = [
                "mongorestore",
                "--uri",
                settings.MONGODB_URL,
                "--nsInclude",
                f"{settings.MONGODB_DB_NAME}.{collection}",
                "--archive=" + str(archive),
                "--gzip",
                "--drop",
            ]
            subprocess.run(dump_cmd, check=True, capture_output=True, text=True)
            await db[collection].delete_one({"_id": drill_id})
            subprocess.run(restore_cmd, check=True, capture_output=True, text=True)
            restored = await db[collection].find_one({"_id": drill_id})
            ok = restored is not None
            return {
                "name": "mongo_backup_restore",
                "ok": ok,
                "detail": "temporary collection restored" if ok else "temporary collection was not restored",
                "collection": collection,
                "archive_bytes": archive.stat().st_size if archive.exists() else 0,
                "method": "mongodump_mongorestore",
            }
    except subprocess.CalledProcessError as exc:
        return {
            "name": "mongo_backup_restore",
            "ok": False,
            "detail": f"{exc.cmd[0]} failed: {exc.stderr or exc.stdout}",
        }
    except Exception as exc:
        return {"name": "mongo_backup_restore", "ok": False, "detail": f"{exc.__class__.__name__}: {exc}"}
    finally:
        try:
            await db[collection].delete_many({})
        finally:
            client.close()


def _artifact_bucket() -> str | None:
    explicit = (os.environ.get("MODEL_ARTIFACT_BUCKET") or "").strip()
    if explicit:
        return explicit
    parsed = urlparse(model_artifact_service.resolve_learned_ranker_uri())
    if parsed.scheme == "s3" and parsed.netloc:
        return parsed.netloc
    return None


def _artifact_drill(*, execute: bool) -> dict[str, Any]:
    if not execute:
        return {"name": "artifact_backup_restore", "ok": True, "skipped": True, "detail": "pass --execute to run the drill"}
    bucket = _artifact_bucket()
    if not bucket:
        return {
            "name": "artifact_backup_restore",
            "ok": False,
            "detail": "MODEL_ARTIFACT_BUCKET or s3:// LEARNED_RANKER_ARTIFACT_URI is required",
        }
    try:
        import boto3  # type: ignore

        session = boto3.session.Session(
            aws_access_key_id=settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY or None,
            region_name=settings.MLOPS_MODEL_ARTIFACT_S3_REGION or None,
        )
        client = session.client(
            "s3",
            endpoint_url=(settings.MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL or None),
        )
        stamp = utc_now().strftime("%Y%m%dT%H%M%S")
        source_key = f"backup-restore-drills/{stamp}/sentinel.txt"
        backup_key = f"backup-restore-drills/{stamp}/backup/sentinel.txt"
        restore_key = f"backup-restore-drills/{stamp}/restore/sentinel.txt"
        body = f"vidyaverse artifact backup restore drill {stamp}\n".encode("utf-8")
        client.put_object(Bucket=bucket, Key=source_key, Body=body)
        client.copy_object(Bucket=bucket, Key=backup_key, CopySource={"Bucket": bucket, "Key": source_key})
        client.delete_object(Bucket=bucket, Key=source_key)
        client.copy_object(Bucket=bucket, Key=restore_key, CopySource={"Bucket": bucket, "Key": backup_key})
        restored = client.get_object(Bucket=bucket, Key=restore_key)["Body"].read()
        ok = restored == body
        return {
            "name": "artifact_backup_restore",
            "ok": ok,
            "detail": "sentinel object restored" if ok else "restored sentinel did not match",
            "bucket": bucket,
            "backup_key": backup_key,
            "restore_key": restore_key,
        }
    except Exception as exc:
        return {"name": "artifact_backup_restore", "ok": False, "detail": f"{exc.__class__.__name__}: {exc}", "bucket": bucket}


async def _run(*, execute: bool, require_mongodump: bool) -> dict[str, Any]:
    checks = [
        await _mongo_drill(execute=execute, require_mongodump=require_mongodump),
        _artifact_drill(execute=execute),
    ]
    return {
        "generated_at": utc_now().isoformat(),
        "executed": bool(execute),
        "ok": all(bool(item["ok"]) for item in checks),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mongo and artifact backup/restore drills with temporary sentinel data.")
    parser.add_argument("--execute", action="store_true", help="Actually write, back up, delete, restore, and verify sentinel data.")
    parser.add_argument("--require-mongodump", action="store_true", help="Fail instead of using a logical fallback when MongoDB Database Tools are unavailable.")
    parser.add_argument("--json-out", type=str, default="backend/benchmarks/backup_restore_drill.json")
    args = parser.parse_args()
    payload = asyncio.run(_run(execute=bool(args.execute), require_mongodump=bool(args.require_mongodump)))
    out_path = Path(args.json_out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok" if payload["ok"] else "failed", "json": str(out_path), "checks": payload["checks"]}, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
