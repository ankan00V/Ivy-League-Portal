"""A Beanie-shaped query layer backed by Postgres.

There are roughly 651 ODM call sites across 87 files. Hand-porting them would
mean 651 chances to introduce a silent fault in auth, dedup or ranking - the
kind that does not raise, it just stops revoking a session or starts admitting
duplicates. Implementing the handful of operations those sites actually use,
once, is both smaller and testable.

The query surface was measured rather than guessed: no filter (138),
`Model.field == value` (101), raw Mongo dicts with operators (17), `In(...)`
(12), comparisons like `>=` and `<` (12), and `*filters` unpacking (20). Writes
are insert, save, replace, delete and insert_many.

That first count was short. It missed `find_one(...).update({...})` (3 sites,
all in the job runner), one `find_one_and_update` for the queue claim, and six
files that reach past the ODM for the raw collection - `count_documents`,
`distinct`, `update_many`, `delete_many`, `aggregate`. Those are covered too,
except aggregate. What looked like `.set()`/`.inc()` call sites in a first grep
turned out to be Prometheus and Redis, not the ODM.

Two deliberate limits, stated because a shim that silently half-works is worse
than one that refuses:

  - An unsupported operator raises rather than returning an empty result. A
    query that quietly matches nothing looks like "no data" and would be found
    much later, by a user.
  - Aggregation pipelines are not implemented. There are four, all analytics
    and vector search, and they stay on their existing path.

The traps found while building this, each of which fails silently rather than
loudly, are documented at the code that handles them: ExpressionField.__eq__
returning an object instead of a bool, `.name` on a field yielding a sub-path,
`$ne: None` meaning IS NOT NULL, and jsonb columns needing a codec.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any, Iterable

from pydantic import BaseModel

import asyncpg

logger = logging.getLogger(__name__)


class UnsupportedQuery(RuntimeError):
    """Raised when a query shape has no Postgres translation.

    Deliberately loud. Returning [] here would read as "nothing matched".
    """


# --------------------------------------------------------------------------
# translating Beanie/Mongo filters into SQL
# --------------------------------------------------------------------------

_OPERATORS = {
    "$eq": "=", "$ne": "<>", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<=",
}


# Beanie's `id` field carries alias `_id`, so `Model.id == x` renders to a
# filter on "_id" - a column that does not exist here. The document identity
# lives in legacy_mongo_id, which is what the migration keyed on.
_ID_KEYS = {"_id", "id"}


def map_key(key: str) -> str:
    """Public alias; the document layer needs the same mapping."""
    return _map_key(key)


def _map_key(key: str) -> str:
    return "legacy_mongo_id" if key in _ID_KEYS else key


def _field_name(field: Any) -> str:
    """Plain column name from a Beanie field reference or a string.

    Beanie's ExpressionField subclasses `str` but overrides `__getattr__` to
    build sub-field paths, so `field.name` returns ExpressionField("x.name")
    rather than "x". Reading `.name` here would silently produce a column that
    does not exist; str() is the only safe way to get the name back.
    """
    return str(field)


def _column(field: Any) -> str:
    name = _field_name(field)
    if "." in name:  # nested paths have no column; they live in extras
        raise UnsupportedQuery(f"nested field path not supported: {name}")
    return f'"{name}"'


def _coerce(value: Any) -> Any:
    if isinstance(value, datetime):
        # Mongo stored naive UTC; timestamptz columns need it explicit.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (str, int, float, bool, date)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    if isinstance(value, BaseModel):
        # Nested models must round-trip as JSON objects. Falling through to
        # str() below wrote Experiment.variants as a list containing
        # "name='ask_ai.v2' weight=1.0 traffic_fraction=None ..." - the repr of
        # the model - which reloads as a str and made every later
        # `v.name for v in experiment.variants` raise AttributeError. That
        # exception surfaced inside ensure_defaults(), which main.py catches and
        # prints, so the RAG template registry silently failed to initialise on
        # every boot while the app reported a clean startup.
        #
        # mode="json" so datetimes and enums inside the nested model become JSON
        # scalars rather than objects psycopg cannot adapt.
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)


def _jsonable(value: Any) -> Any:
    """Convert nested Pydantic models to plain JSON structures, leaving all else alone.

    jsonb columns hand their value straight to the connection's json codec, whose
    serializer falls back to str() for anything it does not recognise. A
    list[ExperimentVariant] therefore persisted as
    ["name='ask_ai.v2' weight=1.0 traffic_fraction=None ..."] - the repr of the
    model. It reloaded as a str, so `v.name` raised AttributeError inside
    ensure_defaults(), and main.py catches and prints that, which is why the RAG
    template registry silently failed to initialise on every boot.

    Only BaseModel instances are rewritten. Everything else is returned
    unchanged so this cannot alter how any existing jsonb payload is stored.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _col_ref(field: str, columns: dict[str, str] | None) -> tuple[str, bool]:
    """SQL reference for a field, and whether it resolves inside `extras`.

    Fields the migration could not map to a column live in the `extras` jsonb
    blob. Without this they render as bare identifiers and Postgres rejects the
    statement - which is how account erasure failed on `posted_by_user_id`.
    """
    if columns is None or field in columns or "extras" not in (columns or {}):
        return f'"{field}"', False
    return f"\"extras\"->>'{field}'", True


def _render_mongo_dict(query: dict, params: list[Any],
                       columns: dict[str, str] | None = None) -> str:
    """Translate a raw Mongo filter dict."""
    parts: list[str] = []
    for raw_key, value in query.items():
        # str() is not cosmetic. Keys arrive as ExpressionField, whose __eq__
        # returns an Eq object rather than a bool - so `raw_key in ("$and",
        # "$or")` is truthy for every field name, and plain equality filters
        # get rendered as boolean groups.
        key = _map_key(str(raw_key))
        if key in ("$and", "$or"):
            joiner = " AND " if key == "$and" else " OR "
            subs = [_render_mongo_dict(sub, params, columns) for sub in value]
            parts.append("(" + joiner.join(subs) + ")")
            continue
        if key.startswith("$"):
            raise UnsupportedQuery(f"top-level operator {key}")

        col, in_extras = _col_ref(key, columns)
        # extras is text on the way out, so operands compare as text too.
        cast = str if in_extras else _coerce
        if isinstance(value, dict):
            for op, operand in value.items():
                if op == "$in":
                    params.append([cast(v) for v in operand])
                    parts.append(f"{col} = ANY(${len(params)})")
                elif op == "$nin":
                    params.append([cast(v) for v in operand])
                    parts.append(f"NOT ({col} = ANY(${len(params)}))")
                elif op == "$exists":
                    parts.append(f"{col} IS {'NOT NULL' if operand else 'NULL'}")
                elif op == "$regex":
                    params.append(str(operand))
                    # Mongo's $regex is case-sensitive unless told otherwise;
                    # the options flag is handled by the caller's pattern.
                    parts.append(f"{col} ~ ${len(params)}")
                elif op in ("$eq", "$ne") and operand is None:
                    # `$ne: None` means "is not null" in Mongo. Rendered as
                    # `col <> NULL` it evaluates to NULL and matches nothing -
                    # no error, just an empty result, so the expiry sweep would
                    # silently stop expiring anything.
                    parts.append(f"{col} IS {'NULL' if op == '$eq' else 'NOT NULL'}")
                elif op in _OPERATORS:
                    params.append(cast(operand))
                    parts.append(f"{col} {_OPERATORS[op]} ${len(params)}")
                else:
                    raise UnsupportedQuery(f"operator {op} on {key}")
        else:
            if value is None:
                parts.append(f"{col} IS NULL")
            else:
                params.append(cast(value))
                parts.append(f"{col} = ${len(params)}")
    return " AND ".join(parts) if parts else "TRUE"


def _render_expression(expr: Any, params: list[Any],
                       columns: dict[str, str] | None = None) -> str:
    """Translate one Beanie comparison expression.

    `Model.field == value` produces an `Eq` object whose `.query` is
    `{"field": value}`; `Model.field < value` produces an `LT` whose query is
    `{"field": {"$lt": value}}`. Beanie's operators subclass Mapping rather than
    dict, so both they and raw filter dicts are covered by the Mapping check -
    an `isinstance(..., dict)` test alone silently misses every one of them.
    """
    if isinstance(expr, str):
        # An ExpressionField on its own carries no comparison.
        raise UnsupportedQuery("string filters are ambiguous")
    if isinstance(expr, Mapping):
        return _render_mongo_dict(dict(expr), params, columns)
    raw = getattr(expr, "query", None)
    if isinstance(raw, Mapping):
        return _render_mongo_dict(dict(raw), params, columns)
    raise UnsupportedQuery(f"unrecognised filter: {type(expr).__name__}")


def build_where(filters: Iterable[Any],
                columns: dict[str, str] | None = None) -> tuple[str, list[Any]]:
    params: list[Any] = []
    clauses = [_render_expression(f, params, columns) for f in filters if f is not None]
    return (" AND ".join(c for c in clauses if c) or "TRUE"), params


def parse_sort(spec: Any) -> str:
    """Beanie sort strings: '-created_at' means descending."""
    if not spec:
        return ""
    # `-Model.field` evaluates to a (field, SortDirection) pair, so a bare
    # 2-tuple is one sort key - not two. Treating it as a list of fields turns
    # the direction into a column name.
    if _is_sort_pair(spec):
        fields = [spec]
    elif isinstance(spec, (list, tuple)):
        fields = list(spec)
    else:
        fields = [spec]

    parts = []
    for field in fields:
        if _is_sort_pair(field):
            name, direction = _map_key(_field_name(field[0])), field[1]
            descending = int(getattr(direction, "value", direction)) < 0
            parts.append(f'"{name}" ' + ("DESC NULLS LAST" if descending else "ASC"))
            continue
        text = _field_name(field)
        if text.startswith("-"):
            parts.append(f'"{_map_key(text[1:])}" DESC NULLS LAST')
        elif text.startswith("+"):
            parts.append(f'"{_map_key(text[1:])}" ASC')
        else:
            parts.append(f'"{_map_key(text)}" ASC')
    return ", ".join(parts)


def _is_sort_pair(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and not isinstance(value[1], str)
        and isinstance(getattr(value[1], "value", value[1]), int)
    )


def render_update(update: Mapping, columns: dict[str, str], params: list[Any]) -> str:
    """Translate a Mongo update document into a SET clause.

    Only `$set` and `$inc` are accepted. Anything else raises: an update that
    silently drops an operator writes a half-correct row, and for the job queue
    that means a job whose status moved but whose lock never cleared.
    """
    assignments: list[str] = []
    # Fields with no column of their own live inside `extras`, where the
    # migration put everything it could not map. Account erasure anonymises
    # such a field, so refusing here would leave personal data in place.
    extras_expr = 'COALESCE("extras", \'{}\'::jsonb)'
    extras_touched = False

    for raw_op, payload in update.items():
        op = str(raw_op)
        if op not in ("$set", "$inc"):
            raise UnsupportedQuery(f"update operator {op}")
        for raw_field, value in payload.items():
            field = _map_key(str(raw_field))
            if field not in columns:
                if "extras" not in columns:
                    raise UnsupportedQuery(f"no column for updated field {field}")
                if op == "$inc":
                    raise UnsupportedQuery(f"$inc on extras field {field}")
                params.append(value)
                extras_expr = (
                    f"jsonb_set({extras_expr}, '{{{field}}}', ${len(params)}::jsonb, true)"
                )
                extras_touched = True
                continue
            params.append(coerce_for_column(value, columns[field]))
            if op == "$inc":
                assignments.append(f'"{field}" = COALESCE("{field}", 0) + ${len(params)}')
            else:
                assignments.append(f'"{field}" = ${len(params)}')

    if extras_touched:
        assignments.append(f'"extras" = {extras_expr}')
    if not assignments:
        raise UnsupportedQuery("empty update document")
    return ", ".join(assignments)


# --------------------------------------------------------------------------
# row <-> model
# --------------------------------------------------------------------------

def record_to_document(record: asyncpg.Record) -> dict[str, Any]:
    """A row as a Mongo-shaped document dict.

    For call sites that hand the result to `Model.model_validate`, which expects
    the `_id` key rather than the Postgres primary key.
    """
    data: dict[str, Any] = {}
    raw = record.get("extras") if "extras" in record.keys() else None
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                data.update(parsed)
        except (ValueError, TypeError):
            pass
    for key in record.keys():
        if key in ("extras", "legacy_mongo_id", "id"):
            continue
        data[key] = record[key]
    legacy = record.get("legacy_mongo_id") if "legacy_mongo_id" in record.keys() else None
    if legacy:
        data["_id"] = legacy
    return data



_VALIDATION_NEEDED: dict[type, bool] = {}


_OBJECTID_FIELDS: dict[type, tuple[str, ...]] = {}


def _objectid_fields(model_cls) -> tuple[str, ...]:
    """Fields typed as a Mongo id, which arrive from Postgres as plain text.

    The fast path below skips Pydantic validation, and validation is what used
    to turn those strings back into PydanticObjectId. Without this the values
    stay `str`, and every join keyed on them silently misses: the leaderboard
    matched 0 of 6 profiles to their users and rendered empty, while the
    dashboard - which never does that join - looked fine.
    """
    cached = _OBJECTID_FIELDS.get(model_cls)
    if cached is not None:
        return cached
    from beanie import PydanticObjectId

    names = []
    for name, field in model_cls.model_fields.items():
        annotation = field.annotation
        candidates = [annotation, *getattr(annotation, "__args__", ())]
        for candidate in candidates:
            if isinstance(candidate, type) and issubclass(candidate, PydanticObjectId):
                names.append(name)
                break
    result = tuple(names)
    _OBJECTID_FIELDS[model_cls] = result
    return result


def _coerce_objectids(model_cls, payload: dict) -> dict:
    from beanie import PydanticObjectId

    for name in _objectid_fields(model_cls):
        value = payload.get(name)
        if isinstance(value, str) and value:
            try:
                payload[name] = PydanticObjectId(value)
            except Exception:
                # Not a valid id: leave it alone rather than lose the value.
                pass
    return payload


def _needs_validation(model_cls) -> bool:
    """Whether this model has fields only validation can rebuild correctly.

    Cached per class: the answer is a property of the model, and the check runs
    on every row read otherwise.
    """
    cached = _VALIDATION_NEEDED.get(model_cls)
    if cached is not None:
        return cached
    from pydantic import BaseModel

    needed = False
    for field in model_cls.model_fields.values():
        annotation = field.annotation
        candidates = [annotation, *getattr(annotation, "__args__", ())]
        for candidate in candidates:
            inner = getattr(candidate, "__args__", ())
            candidates_inner = [candidate, *inner]
            for value in candidates_inner:
                if isinstance(value, type) and issubclass(value, BaseModel):
                    needed = True
                    break
            if needed:
                break
        if needed:
            break
    _VALIDATION_NEEDED[model_cls] = needed
    return needed


def record_to_model(model_cls, record: asyncpg.Record):
    """Rebuild a model instance, merging `extras` under the real columns."""
    from beanie import PydanticObjectId

    data: dict[str, Any] = {}
    raw = record.get("extras") if "extras" in record.keys() else None
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                data.update(parsed)
        except (ValueError, TypeError):
            pass
    for key in record.keys():
        if key in ("extras", "legacy_mongo_id", "id"):
            continue
        value = record[key]
        if value is not None:
            data[key] = list(value) if isinstance(value, (list, tuple)) else value

    known = set(model_cls.model_fields)
    payload = {k: v for k, v in data.items() if k in known}
    if _needs_validation(model_cls):
        try:
            # Validation, not model_construct, so nested models are rebuilt as
            # models. A jsonb column decodes to plain dicts, and model_construct
            # keeps them that way - `experiment.variants` came back as a list of
            # dicts and `v.name` raised on every one.
            instance = model_cls.model_validate(payload)
        except Exception:
            # Rows migrated from Mongo can carry values a stricter model now
            # rejects. Those must still load, or the whole read fails on one row.
            instance = model_cls.model_construct(**payload)
    else:
        # No nested models to rebuild, so validation buys nothing and costs a
        # lot: the vector index rebuild reads ~1,880 rows at a time on the event
        # loop, and paying full validation for each one starved every concurrent
        # request. Id fields still need converting, since that is the one thing
        # validation did here that callers depend on.
        instance = model_cls.model_construct(**_coerce_objectids(model_cls, payload))
    legacy = record.get("legacy_mongo_id") if "legacy_mongo_id" in record.keys() else None
    if legacy:
        try:
            instance.id = PydanticObjectId(legacy)
        except Exception:
            instance.id = None
    # Row identity, so save()/replace() know which row to write back to.
    object.__setattr__(instance, "_pg_row_id", record.get("id"))
    return instance


def is_vector_column(data_type: str) -> bool:
    return data_type in ("USER-DEFINED", "vector")


def coerce_for_column(value: Any, data_type: str) -> Any:
    """Coerce a Python value to what the column's type will accept."""
    if value is None:
        return None
    if is_vector_column(data_type):
        # Passed through as a list: the connection registers a pgvector codec
        # that renders the literal form. Encoding here as well would produce a
        # string the codec then re-encodes.
        if isinstance(value, str):
            return value or None
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            return None
    if data_type in ("json", "jsonb"):
        # Passed through as a Python object: the connection registers a json
        # codec, so encoding here would produce a JSON string containing JSON.
        # Nested Pydantic models are the one thing that codec cannot handle -
        # see _jsonable.
        return _jsonable(value)
    if data_type == "ARRAY":
        return [_coerce(v) for v in value] if isinstance(value, (list, tuple, set)) else None
    if data_type == "boolean":
        return bool(value)
    if data_type in ("integer", "bigint", "smallint"):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if data_type in ("double precision", "real", "numeric"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return _coerce(value)


def model_to_values(instance, columns: dict[str, str]) -> list[Any]:
    values = []
    for col, data_type in columns.items():
        if col == "legacy_mongo_id":
            raw = getattr(instance, "id", None)
            values.append(str(raw) if raw else None)
        elif col == "extras":
            known = set(type(instance).model_fields)
            # `id` is excluded: it is stored in legacy_mongo_id, and keeping a
            # second copy in extras lets the two drift.
            leftover = {
                k: v for k, v in instance.__dict__.items()
                if k in known and k not in columns and k != "id" and not k.startswith("_")
            }
            values.append(leftover)
        else:
            values.append(coerce_for_column(getattr(instance, col, None), data_type))
    return values
