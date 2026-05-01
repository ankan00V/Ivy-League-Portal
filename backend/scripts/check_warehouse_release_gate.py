from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.warehouse_export_run import WarehouseExportRun
from app.services.warehouse_export_service import warehouse_export_service


def _client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
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


async def _run() -> dict[str, Any]:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_client_kwargs())
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[WarehouseExportRun],
    )
    try:
        return await warehouse_export_service.freshness_status()
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail release when required analytics marts are missing or stale.")
    parser.add_argument("--json", action="store_true", help="Print full freshness payload as JSON.")
    args = parser.parse_args()

    status = asyncio.run(_run())
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(
            "warehouse_freshness "
            f"status={status.get('status')} "
            f"fresh={status.get('fresh')} "
            f"missing={status.get('missing_marts')} "
            f"stale={status.get('stale_marts')} "
            f"age_minutes={status.get('age_minutes')}"
        )
    if not bool(settings.ANALYTICS_WAREHOUSE_ENFORCE_FRESHNESS_IN_PRODUCTION):
        return
    if not bool(status.get("fresh")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
