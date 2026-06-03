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
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.models.duplicate_merge_event import DuplicateMergeEvent  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.services.duplicate_detector import duplicate_detector  # noqa: E402


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


async def _run(*, limit: int, execute: bool, mark_duplicate_closed: bool) -> dict[str, Any]:
    client = AsyncIOMotorClient(settings.MONGODB_URL, **_mongo_client_kwargs())
    try:
        await init_beanie(
            database=client[settings.MONGODB_DB_NAME],
            document_models=[Opportunity, DuplicateMergeEvent],
        )
        return await duplicate_detector.scan_existing(
            limit=limit,
            execute=execute,
            mark_duplicate_closed=mark_duplicate_closed,
        )
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retroactive opportunity deduplication.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum opportunities to scan.")
    parser.add_argument("--execute", action="store_true", help="Persist merges instead of dry-running.")
    parser.add_argument(
        "--close-duplicates",
        action="store_true",
        help="Mark duplicate rows closed when --execute is used.",
    )
    parser.add_argument("--json-out", type=str, default="", help="Optional path to write the scan report.")
    args = parser.parse_args()

    payload = asyncio.run(
        _run(
            limit=max(1, int(args.limit)),
            execute=bool(args.execute),
            mark_duplicate_closed=bool(args.close_duplicates and args.execute),
        )
    )

    output = json.dumps(payload, indent=2, sort_keys=True)
    print(output)
    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
