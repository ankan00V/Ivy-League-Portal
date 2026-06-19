#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database
from app.services.company_careers_intelligence import company_careers_intelligence_service


async def _run(args: argparse.Namespace) -> dict:
    client = await init_database()
    try:
        company_names = [item.strip() for item in args.company for item in item.split(",") if item.strip()]
        return await company_careers_intelligence_service.ingest_seeded_company_careers(
            limit=int(args.limit),
            company_names=company_names,
            dry_run=bool(args.dry_run),
        )
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and ingest official company career opportunities.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--company", action="append", default=[], help="Company name filter; can be repeated or comma-separated.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
