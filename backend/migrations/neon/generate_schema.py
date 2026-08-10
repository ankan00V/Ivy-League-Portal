"""Derive the Postgres schema from the Beanie models.

Fifty-six collections is too many to hand-write without mistakes, and a
hand-written schema drifts the moment a model changes. Reading the models
directly means the schema is a function of the code rather than a parallel
description of it, and re-running this after a model change regenerates the
truth instead of a guess.

Mapping rules, and why:

  scalars          -> typed columns. These are what gets filtered and sorted on,
                      and a typed column is what makes an index useful.
  list[str|int]    -> native Postgres arrays. Postgres indexes and queries these
                      directly, so burying them in jsonb would lose that.
  list[dict], dict -> jsonb. No query in this codebase reaches inside them.
  datetime         -> timestamptz. Mongo stores naive UTC; making the zone
                      explicit prevents a silent shift.
  PydanticObjectId -> text. Foreign keys are deliberately not declared: Mongo
                      never enforced them, so some references are already
                      dangling and a real constraint would reject that data on
                      import rather than let it be cleaned up afterwards.

Every model also keeps `legacy_mongo_id` so a migrated row stays traceable to
its source document, and `extras` so a field added to a model tomorrow does not
silently vanish on the way across.
"""

from __future__ import annotations

import sys
import types
import typing
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.bootstrap import DOCUMENT_MODELS  # noqa: E402

RESERVED = {
    "id", "legacy_mongo_id", "extras",
    # Postgres keywords that would need quoting everywhere they appear.
    "order", "user", "group", "references", "default", "limit", "offset",
    "table", "column", "select", "where", "from", "to", "end", "start",
}


def _unwrap(annotation):
    """Strip Optional/Union down to the underlying type."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else None
    return annotation


def sql_type(annotation) -> str:
    """Postgres type for a pydantic annotation, defaulting to jsonb."""
    inner = _unwrap(annotation)
    if inner is None:
        return "jsonb"
    origin = typing.get_origin(inner)

    if origin in (list, set, tuple):
        args = typing.get_args(inner)
        item = _unwrap(args[0]) if args else None
        if item is str:
            return "text[]"
        if item is int:
            return "integer[]"
        if item is float:
            return "double precision[]"
        # list[dict] or list[Model]: no query reaches inside these.
        return "jsonb"
    if origin is dict:
        return "jsonb"

    if inner is bool:
        return "boolean"
    if inner is int:
        return "bigint"
    if inner is float:
        return "double precision"
    if inner is datetime:
        return "timestamptz"
    if inner is date:
        return "date"
    if inner is str:
        return "text"

    name = getattr(inner, "__name__", "")
    if name in ("PydanticObjectId", "ObjectId"):
        return "text"
    if name in ("Decimal",):
        return "numeric"
    # Nested pydantic models and anything unrecognised.
    return "jsonb"


def table_name(model) -> str:
    settings = getattr(model, "Settings", None)
    name = getattr(settings, "name", None) if settings else None
    return name or model.__name__.lower()


def column_name(field: str) -> str:
    return f'"{field}"' if field in RESERVED else field


def ddl_for(model) -> tuple[str, list[str]]:
    table = table_name(model)
    lines = [
        "    id                uuid PRIMARY KEY DEFAULT gen_random_uuid()",
        "    , legacy_mongo_id text UNIQUE",
    ]
    seen: set[str] = set()
    for field, info in model.model_fields.items():
        if field in ("id", "revision_id"):
            continue
        if field in seen:
            continue
        seen.add(field)
        col = column_name(field)
        typ = sql_type(info.annotation)
        default = ""
        if typ.endswith("[]"):
            default = " DEFAULT '{}'"
        elif typ == "jsonb":
            default = " DEFAULT '{}'::jsonb"
        lines.append(f"    , {col} {typ}{default}")
    # Anything the model gains later, or that a document carries but the model
    # does not declare.
    lines.append("    , extras jsonb NOT NULL DEFAULT '{}'::jsonb")

    create = f"CREATE TABLE IF NOT EXISTS app.{table} (\n" + "\n".join(lines) + "\n);"

    # Recreate the indexes the model declared for Mongo, so access patterns that
    # were already known to matter stay cheap.
    indexes: list[str] = []
    settings = getattr(model, "Settings", None)
    for raw in (getattr(settings, "indexes", None) or []):
        keys = getattr(raw, "document", None) or getattr(raw, "_doc", None)
        spec = None
        if isinstance(raw, (list, tuple)):
            spec = raw
        elif isinstance(keys, dict) and "key" in keys:
            spec = list(keys["key"].items())
        if not spec:
            continue
        cols = []
        for entry in spec:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                name, direction = entry
                if name in ("_id",) or name not in model.model_fields:
                    cols = []
                    break
                cols.append(f"{column_name(name)} {'DESC' if direction == -1 else 'ASC'}")
        if not cols:
            continue
        idx_name = f"{table}_{'_'.join(c.split()[0].strip(chr(34)) for c in cols)}_idx"[:60]
        indexes.append(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON app.{table} ({', '.join(cols)});"
        )
    return create, indexes


def main() -> None:
    out = [
        "-- GENERATED by migrations/neon/generate_schema.py - do not hand-edit.",
        "-- Regenerate after changing any Beanie model.",
        "CREATE SCHEMA IF NOT EXISTS app;",
        "CREATE EXTENSION IF NOT EXISTS vector;",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
        "",
    ]
    skipped = []
    for model in DOCUMENT_MODELS:
        table = table_name(model)
        # opportunities is hand-written in 001: it carries the pgvector column
        # and the feed's compound indexes, which matter more than uniformity.
        if table == "opportunities":
            skipped.append(table)
            continue
        create, indexes = ddl_for(model)
        out.append(f"-- {model.__name__}")
        out.append(create)
        out.extend(indexes)
        out.append("")
    path = Path(__file__).parent / "002_generated_schema.sql"
    path.write_text("\n".join(out))
    print(f"  models: {len(DOCUMENT_MODELS)}   generated: {len(DOCUMENT_MODELS)-len(skipped)}   skipped: {skipped}")
    print(f"  wrote {path.name} ({len(out)} lines)")


if __name__ == "__main__":
    main()
