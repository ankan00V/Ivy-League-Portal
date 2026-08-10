"""Copy every Mongo collection into its Neon table.

Driven by the same model list the schema generator used, so the two cannot drift
apart: a model that exists has a table, and a table that exists gets migrated.

Two properties matter more than speed here.

Idempotent. Every row upserts on `legacy_mongo_id`, so a re-run converges rather
than duplicating, and the script can be run repeatedly while Mongo is still
taking writes.

Lossless. Any document field that has no column - because the document predates
a model change, or carries something the model never declared - is folded into
`extras` instead of being dropped. Nothing silently disappears in transit, which
is the failure mode that makes a migration impossible to audit afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
ENV = dotenv_values(BACKEND / ".env")

from app.bootstrap import DOCUMENT_MODELS  # noqa: E402

# Handled by migrate_opportunities.py, which knows about the pgvector column.
SKIP = {"opportunities"}


def target_dsn() -> str:
    """Connection string for the migration target.

    Supabase first, Neon second: Neon has no India region and measured 130ms per
    query from Singapore against 44ms here, so Supabase took over as the target.
    The Neon entries stay in .env, commented, so that project remains usable.
    """
    dsn = ENV.get("SUPABASE_DATABASE_DIRECT_URL") or ENV.get("NEON_DATABASE_DIRECT_URL")
    if not dsn:
        raise SystemExit("no SUPABASE_DATABASE_DIRECT_URL or NEON_DATABASE_DIRECT_URL in .env")
    return dsn.replace("?sslmode=require", "")

def table_name(model) -> str:
    settings = getattr(model, "Settings", None)
    return (getattr(settings, "name", None) if settings else None) or model.__name__.lower()


def _json_safe(value: Any) -> Any:
    """ObjectId, datetime and friends are not JSON types."""
    return json.loads(json.dumps(value, default=str))


def coerce(value: Any, pg_type: str) -> Any:
    if value is None:
        return None
    if pg_type == "timestamptz":
        if isinstance(value, datetime):
            # Mongo stores naive UTC; leaving it naive would shift the value.
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return None
    if pg_type == "date":
        return value if isinstance(value, date) and not isinstance(value, datetime) else None
    if pg_type == "jsonb":
        return json.dumps(_json_safe(value))
    if pg_type == "text[]":
        return [str(x) for x in value] if isinstance(value, (list, tuple, set)) else None
    if pg_type == "integer[]":
        return [int(x) for x in value if isinstance(x, (int, float))] if isinstance(value, (list, tuple)) else None
    if pg_type == "double precision[]":
        return [float(x) for x in value if isinstance(x, (int, float))] if isinstance(value, (list, tuple)) else None
    if pg_type == "boolean":
        return bool(value)
    if pg_type == "bigint":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if pg_type in ("double precision", "numeric"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if pg_type == "text":
        return value if isinstance(value, str) else str(value)
    return value


async def column_types(pg: asyncpg.Connection, table: str) -> dict[str, str]:
    rows = await pg.fetch(
        """
        SELECT column_name,
               CASE
                 WHEN data_type = 'ARRAY' THEN
                   CASE udt_name
                     WHEN '_text' THEN 'text[]'
                     WHEN '_int4' THEN 'integer[]'
                     WHEN '_float8' THEN 'double precision[]'
                     ELSE 'jsonb' END
                 WHEN data_type = 'timestamp with time zone' THEN 'timestamptz'
                 WHEN data_type = 'double precision' THEN 'double precision'
                 WHEN data_type IN ('bigint','integer','smallint') THEN 'bigint'
                 WHEN data_type = 'boolean' THEN 'boolean'
                 WHEN data_type = 'jsonb' THEN 'jsonb'
                 WHEN data_type = 'date' THEN 'date'
                 ELSE 'text' END AS pg_type
        FROM information_schema.columns
        WHERE table_schema = 'app' AND table_name = $1
        """,
        table,
    )
    return {r["column_name"]: r["pg_type"] for r in rows}


async def migrate_collection(mongo_db, pg: asyncpg.Connection, model, batch_size: int) -> dict[str, Any]:
    table = table_name(model)
    types = await column_types(pg, table)
    if not types:
        return {"table": table, "status": "no_table"}

    cols = [c for c in types if c not in ("id",)]
    mapped = set(cols) - {"legacy_mongo_id", "extras"}

    placeholders = ", ".join(
        f"${i+1}::jsonb" if types[c] == "jsonb" else f"${i+1}" for i, c in enumerate(cols)
    )
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c != "legacy_mongo_id")
    sql = (
        f'INSERT INTO app.{table} ({", ".join(chr(34)+c+chr(34) for c in cols)}) '
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (legacy_mongo_id) DO UPDATE SET {updates}"
    )

    collection = mongo_db[table]
    total = await collection.count_documents({})
    if total == 0:
        return {"table": table, "mongo": 0, "migrated": 0, "status": "empty"}

    migrated = 0
    batch: list[tuple] = []
    async for doc in collection.find({}):
        # Fields with no column of their own are preserved rather than dropped.
        leftover = {k: v for k, v in doc.items() if k != "_id" and k not in mapped}
        row = []
        for c in cols:
            if c == "legacy_mongo_id":
                row.append(str(doc.get("_id")))
            elif c == "extras":
                row.append(json.dumps(_json_safe(leftover)))
            else:
                row.append(coerce(doc.get(c), types[c]))
        batch.append(tuple(row))
        if len(batch) >= batch_size:
            await pg.executemany(sql, batch)
            migrated += len(batch)
            batch = []
    if batch:
        await pg.executemany(sql, batch)
        migrated += len(batch)

    landed = await pg.fetchval(f"SELECT count(*) FROM app.{table}")
    return {"table": table, "mongo": total, "migrated": migrated, "neon": landed,
            "status": "ok" if landed >= total else "short"}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    mongo = AsyncIOMotorClient(ENV["MONGODB_URL"], serverSelectionTimeoutMS=30000,
                               socketTimeoutMS=300000)
    db = mongo[ENV.get("MONGODB_DB_NAME", "vidyaverse")]
    pg: asyncpg.Connection | None = None

    async def fresh() -> asyncpg.Connection:
        # statement_cache_size=0: Supabase fronts Postgres with pgbouncer, which
        # does not support asyncpg's cached prepared statements.
        return await asyncpg.connect(
            target_dsn(), ssl="require", timeout=90, command_timeout=300,
            statement_cache_size=0,
        )

    results = []
    for model in DOCUMENT_MODELS:
        table = table_name(model)
        if table in SKIP or (args.only and args.only != table):
            continue
        # One connection per collection, retried. Holding a single connection
        # for the whole run meant a single network drop during the 30k-row
        # interactions table cascaded into 35 "connection is closed" failures -
        # every table after it was reported broken when only the link was.
        res = None
        for attempt in range(1, 4):
            try:
                if pg is None or pg.is_closed():
                    pg = await fresh()
                res = await migrate_collection(db, pg, model, args.batch)
                break
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError,
                    asyncio.TimeoutError) as exc:
                # Transport-level: drop the connection and try again.
                try:
                    if pg and not pg.is_closed():
                        await pg.close()
                except Exception:
                    pass
                pg = None
                if attempt == 3:
                    res = {"table": table, "status": "error",
                           "error": f"{type(exc).__name__} after 3 attempts"}
                else:
                    await asyncio.sleep(2 * attempt)
            except Exception as exc:
                res = {"table": table, "status": "error",
                       "error": f"{type(exc).__name__}: {exc}"[:180]}
                break
        results.append(res)
        if res.get("status") not in ("empty",):
            print(f"  {res['table']:<38} {res.get('mongo',0):>6} -> {res.get('neon',0):>6}  {res['status']}", flush=True)
            if res.get("error"):
                print(f"      {res['error']}", flush=True)

    ok = [r for r in results if r["status"] == "ok"]
    empty = [r for r in results if r["status"] == "empty"]
    bad = [r for r in results if r["status"] in ("short", "error", "no_table")]
    print(f"\n  tables ok={len(ok)}  empty={len(empty)}  problems={len(bad)}")
    for r in bad:
        print(f"    PROBLEM {r['table']}: {r.get('error') or r['status']}")
    if pg and not pg.is_closed():
        await pg.close()
    mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
