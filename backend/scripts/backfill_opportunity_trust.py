from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.services.opportunity_trust_backfill import backfill_opportunity_trust


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Persist trust scores and moderation states for existing opportunities.")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    try:
        await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=[Opportunity])
        payload = await backfill_opportunity_trust(batch_size=args.batch_size, limit=args.limit)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
