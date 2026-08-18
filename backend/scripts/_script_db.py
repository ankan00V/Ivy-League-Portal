"""One correct way for a script to reach the serving database.

Scripts in this directory each opened their own `AsyncIOMotorClient(MONGODB_URL)`
and called `init_beanie`. That was right until the Postgres cutover, after which
it silently pointed every one of them at an abandoned database whose newest
interaction is 2026-06-03.

The failure is quiet by construction. The queries succeed, the row counts are
simply small or zero, and the job reports success:

- `publish_dataset_snapshot` published a "Verified Snapshot" of the dead database.
- `purge_aged_telemetry` reported a clean retention run having deleted nothing.
- `rebuild_analytics_warehouse` reported `status: ok` with `feature_rows: 0`,
  which meant the ranker's training data quietly stopped being produced.

Three instances of one mistake, so the fix is a shared entrypoint rather than a
third patch. `connect()` returns the Mongo client when Mongo is serving and
`None` when Postgres is, and callers close it with `close()` which tolerates
either. `tests/test_script_database_targets.py` fails the build if a new script
reintroduces the hardcoded pattern.
"""

from __future__ import annotations

from typing import Any, Optional

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings


def _mongo_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        getattr(settings, "MONGODB_TLS_FORCE", False)
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
    )
    if not tls_needed:
        return {}
    return {
        "tls": True,
        "tlsCAFile": certifi.where(),
        "tlsAllowInvalidCertificates": bool(
            getattr(settings, "MONGODB_TLS_ALLOW_INVALID_CERTS", False)
        ),
    }


async def connect(models: list) -> Optional[AsyncIOMotorClient]:
    """Bind `models` to whichever database is serving.

    Returns the Mongo client when Mongo is serving, or None under
    POSTGRES_ODM_ENABLED - there is no client to hand back because Mongo is never
    contacted. Pass the result to `close()`.
    """
    if settings.POSTGRES_ODM_ENABLED:
        from app.db import pg_documents

        pg_documents.install(models)
        return None

    client = AsyncIOMotorClient(settings.MONGODB_URL, **_mongo_kwargs())
    await init_beanie(database=client[settings.MONGODB_DB_NAME], document_models=models)
    return client


def close(client: Optional[AsyncIOMotorClient]) -> None:
    """Close a client that may legitimately be None."""
    if client is not None:
        client.close()


def serving_backend() -> str:
    """Which database this process will actually read. Worth logging in reports."""
    return "postgres" if settings.POSTGRES_ODM_ENABLED else "mongo"
