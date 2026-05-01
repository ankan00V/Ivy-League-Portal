from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import analytics_bi_tool_url, settings
from app.core.time import utc_now
from app.services.model_artifact_service import model_artifact_service


def _status(name: str, ok: bool, detail: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": detail,
        "metadata": dict(metadata or {}),
    }


def _mongo_client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip().lower()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url
    )
    if not tls_needed:
        return {}
    return {
        "tls": True,
        "tlsCAFile": certifi.where(),
        "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
    }


def _is_local_url(value: str, *, schemes: tuple[str, ...]) -> bool:
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme.lower() not in schemes:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1", "mongo", "redis", "clickhouse", "minio"}


async def _check_mongo(*, require_managed: bool) -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip()
    if not url:
        return _status("mongo", False, "MONGODB_URL is empty")
    if require_managed and _is_local_url(url, schemes=("mongodb", "mongodb+srv")):
        return _status("mongo", False, "MONGODB_URL points at local/dev infrastructure")
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=8000, **_mongo_client_kwargs())
    try:
        await client.admin.command("ping")
        return _status("mongo", True, "ping ok", {"db": settings.MONGODB_DB_NAME})
    except Exception as exc:
        return _status("mongo", False, f"ping failed: {exc.__class__.__name__}: {exc}")
    finally:
        client.close()


async def _check_redis(*, require_managed: bool) -> dict[str, Any]:
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return _status("redis", False, "REDIS_URL is empty")
    if require_managed and _is_local_url(url, schemes=("redis", "rediss")):
        return _status("redis", False, "REDIS_URL points at local/dev infrastructure")
    try:
        from redis.asyncio import Redis  # type: ignore

        client = Redis.from_url(url, socket_connect_timeout=8, socket_timeout=8)
        try:
            pong = await client.ping()
            return _status("redis", bool(pong), "ping ok" if pong else "ping returned false")
        finally:
            await client.aclose()
    except Exception as exc:
        return _status("redis", False, f"ping failed: {exc.__class__.__name__}: {exc}")


def _check_clickhouse(*, require_managed: bool) -> dict[str, Any]:
    host = (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST or "").strip()
    if not settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED:
        return _status("clickhouse", False, "ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED is false")
    if not host:
        return _status("clickhouse", False, "ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST is empty")
    if require_managed and host.lower() in {"localhost", "127.0.0.1", "::1", "clickhouse"}:
        return _status("clickhouse", False, "ClickHouse host points at local/dev infrastructure")
    try:
        import clickhouse_connect  # type: ignore

        client = clickhouse_connect.get_client(
            host=host,
            port=int(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT),
            username=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME or "default",
            password=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD or "",
            database=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE,
            secure=bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE),
            connect_timeout=8,
            send_receive_timeout=8,
        )
        value = client.query("SELECT 1").first_row[0]
        return _status("clickhouse", value == 1, "SELECT 1 ok", {"database": settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE})
    except Exception as exc:
        return _status("clickhouse", False, f"query failed: {exc.__class__.__name__}: {exc}")


def _artifact_bucket_key() -> tuple[str | None, str | None]:
    explicit_bucket = (os.environ.get("MODEL_ARTIFACT_BUCKET") or "").strip()
    if explicit_bucket:
        return explicit_bucket, None
    uri = model_artifact_service.resolve_learned_ranker_uri()
    parsed = urlparse(uri)
    if parsed.scheme == "s3" and parsed.netloc:
        return parsed.netloc, parsed.path.lstrip("/") or None
    return None, None


def _check_artifact_store(*, require_managed: bool) -> dict[str, Any]:
    bucket, key = _artifact_bucket_key()
    if not bucket:
        return _status("artifact_store", False, "MODEL_ARTIFACT_BUCKET or s3:// LEARNED_RANKER_ARTIFACT_URI is required")
    endpoint_url = (settings.MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL or "").strip() or None
    if require_managed and endpoint_url:
        parsed = urlparse(endpoint_url)
        if (parsed.hostname or "").strip().lower() in {"localhost", "127.0.0.1", "::1", "minio"}:
            return _status("artifact_store", False, "S3 endpoint points at local/dev infrastructure")
    try:
        import boto3  # type: ignore

        session = boto3.session.Session(
            aws_access_key_id=settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY or None,
            region_name=settings.MLOPS_MODEL_ARTIFACT_S3_REGION or None,
        )
        client = session.client("s3", endpoint_url=endpoint_url)
        if key:
            client.head_object(Bucket=bucket, Key=key)
            detail = "artifact head ok"
        else:
            client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            detail = "bucket list ok"
        return _status("artifact_store", True, detail, {"bucket": bucket, "key": key})
    except Exception as exc:
        return _status("artifact_store", False, f"S3 check failed: {exc.__class__.__name__}: {exc}", {"bucket": bucket, "key": key})


def _check_bi_tool() -> dict[str, Any]:
    url = analytics_bi_tool_url()
    if not url:
        return _status("bi_tool", False, "ANALYTICS_BI_TOOL_URL is empty")
    try:
        import urllib.request

        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
            ok = 200 <= int(response.status) < 500
            return _status("bi_tool", ok, f"HTTP {response.status}", {"url": url})
    except Exception as exc:
        return _status("bi_tool", False, f"BI URL check failed: {exc.__class__.__name__}: {exc}", {"url": url})


async def _run(*, require_managed: bool, include_bi: bool) -> dict[str, Any]:
    checks = [
        await _check_mongo(require_managed=require_managed),
        await _check_redis(require_managed=require_managed),
        _check_clickhouse(require_managed=require_managed),
        _check_artifact_store(require_managed=require_managed),
    ]
    if include_bi:
        checks.append(_check_bi_tool())
    return {
        "generated_at": utc_now().isoformat(),
        "require_managed": bool(require_managed),
        "ok": all(bool(item["ok"]) for item in checks),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify production-managed Mongo, Redis, ClickHouse, artifact store, and BI wiring.")
    parser.add_argument("--allow-local", action="store_true", help="Allow local Docker endpoints for a developer smoke test.")
    parser.add_argument("--include-bi", action="store_true", help="Also check ANALYTICS_BI_TOOL_URL.")
    parser.add_argument("--json-out", type=str, default="backend/benchmarks/production_infra_readiness.json")
    args = parser.parse_args()

    payload = asyncio.run(_run(require_managed=not args.allow_local, include_bi=bool(args.include_bi)))
    out_path = Path(args.json_out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok" if payload["ok"] else "failed", "json": str(out_path), "checks": payload["checks"]}, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
