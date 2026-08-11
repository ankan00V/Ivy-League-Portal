"""Runs Beanie-shaped queries against Postgres and patches the models onto it.

`pg_odm` translates filters; this executes them and exposes the same chain the
call sites already use - `.sort(...).limit(...).to_list()`, `.count()`,
`.delete()` - plus the write methods on the instances.

Patching rather than rewriting is the point. There are roughly 651 call sites,
and each hand-edit is an opportunity for a silent fault in auth or dedup. The
models keep their Beanie shape; only what happens underneath changes.

Enabled by POSTGRES_ODM_ENABLED. With it off, nothing here is installed and
Beanie behaves exactly as before, so the switch is reversible at runtime rather
than by redeploying.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import asyncpg

from app.core.config import settings
from app.db.pg_odm import (
    UnsupportedQuery,
    build_where,
    is_vector_column,
    map_key as _map_key,
    model_to_values,
    parse_sort,
    record_to_document,
    record_to_model,
    render_update,
)

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
# table -> {column: data_type}. Types matter on write: a dict bound to a jsonb
# column has to be JSON text, and str() of a dict is Python repr, which
# Postgres rejects.
_columns_cache: dict[str, dict[str, str]] = {}


def _pool_size() -> int:
    """Fixed pool width, opened eagerly. See get_pool for why it never grows."""
    return max(4, int(settings.NEON_POOL_MAX_SIZE))


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:  # type: ignore[attr-defined]
        dsn = settings.SUPABASE_DATABASE_URL or settings.NEON_DATABASE_URL
        if not dsn:
            raise RuntimeError("no Postgres URL configured")
        _pool = await asyncpg.create_pool(
            dsn.replace("?sslmode=require", ""),
            ssl="require",
            # min_size == max_size on purpose. Opening a connection resolves
            # the host, and a scrape keeps the resolver busy enough that the
            # lookup fails outright - `gaierror` from _get_new_connection, mid
            # run, which left background jobs stuck in 'running' because the
            # runner could not even write their result back. A pool that opens
            # every connection up front, while DNS is healthy, never grows and
            # so never needs a lookup again.
            min_size=_pool_size(),
            max_size=_pool_size(),
            command_timeout=float(settings.NEON_COMMAND_TIMEOUT_SECONDS),
            # Supabase fronts Postgres with pgbouncer, which does not support
            # asyncpg's cached prepared statements.
            statement_cache_size=0,
            init=_register_codecs,
        )
    return _pool


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """Make json/jsonb columns behave like the dicts the models declare.

    Without this asyncpg hands back raw JSON text, and a model field typed
    `dict` fails validation on the way out - which is how a claimed job arrives
    with payload='{}' as a string.
    """
    import json as _json

    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            # default=str because model payloads carry ObjectId and datetime,
            # neither of which json.dumps handles on its own.
            encoder=lambda v: _json.dumps(v, default=str),
            decoder=_json.loads,
            schema="pg_catalog",
        )


async def close_pool() -> None:
    global _pool
    if _pool is not None and not _pool._closed:  # type: ignore[attr-defined]
        await _pool.close()
    _pool = None


def table_of(model_cls) -> str:
    s = getattr(model_cls, "Settings", None)
    return (getattr(s, "name", None) if s else None) or model_cls.__name__.lower()


async def columns_of(table: str) -> dict[str, str]:
    """Column names in ordinal order, mapped to their Postgres data type."""
    if table not in _columns_cache:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='app' AND table_name=$1 ORDER BY ordinal_position",
                table,
            )
        if not rows:
            raise UnsupportedQuery(f"no app.{table} table in Postgres")
        _columns_cache[table] = {r["column_name"]: r["data_type"] for r in rows}
    return _columns_cache[table]


class PgQuery:
    """The subset of Beanie's query chain the codebase actually uses."""

    def __init__(self, model_cls, filters: tuple, single: bool = False):
        self.model_cls = model_cls
        self.filters = [f for f in filters if f is not None]
        self._sort = ""
        self._limit: int | None = None
        self._skip = 0
        # find_one returns one of these too, because Beanie's find_one is an
        # awaitable query rather than a coroutine - `find_one(...).update(...)`
        # is a real call site and would break against a bare coroutine.
        self._single = single

    def sort(self, *spec):
        self._sort = parse_sort(list(spec) if len(spec) > 1 else (spec[0] if spec else None))
        return self

    def limit(self, n: int):
        self._limit = int(n)
        return self

    def skip(self, n: int):
        self._skip = int(n)
        return self

    async def _where(self):
        # Columns are needed before rendering: a field with no column of its
        # own has to resolve inside extras rather than as a bare identifier.
        return build_where(self.filters, await columns_of(table_of(self.model_cls)))

    async def to_list(self, length: int | None = None) -> list:
        table = table_of(self.model_cls)
        where, params = await self._where()
        sql = f'SELECT * FROM app."{table}" WHERE {where}'
        if self._sort:
            sql += f" ORDER BY {self._sort}"
        effective = length or self._limit
        if effective:
            params.append(int(effective))
            sql += f" LIMIT ${len(params)}"
        if self._skip:
            params.append(int(self._skip))
            sql += f" OFFSET ${len(params)}"
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [record_to_model(self.model_cls, r) for r in rows]

    async def first_or_none(self):
        rows = await self.limit(1).to_list()
        return rows[0] if rows else None

    async def count(self) -> int:
        table = table_of(self.model_cls)
        where, params = await self._where()
        pool = await get_pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval(
                f'SELECT count(*) FROM app."{table}" WHERE {where}', *params
            ) or 0)

    async def delete(self):
        table = table_of(self.model_cls)
        where, params = await self._where()
        pool = await get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f'DELETE FROM app."{table}" WHERE {where}', *params
            )
        # asyncpg returns "DELETE <n>"; callers read .deleted_count.
        deleted = int(status.rsplit(" ", 1)[-1]) if status else 0
        return type("DeleteResult", (), {"deleted_count": deleted})()

    async def update(self, update_doc, **_kw):
        """Apply a Mongo update document to the matched rows."""
        table = table_of(self.model_cls)
        columns = await columns_of(table)
        where, params = await self._where()
        assignments = render_update(dict(update_doc), columns, params)
        if self._single:
            # Mongo's find_one().update() touches exactly one document; a bare
            # UPDATE ... WHERE would touch every match.
            sql = (
                f'UPDATE app."{table}" SET {assignments} WHERE id = '
                f'(SELECT id FROM app."{table}" WHERE {where} LIMIT 1)'
            )
        else:
            sql = f'UPDATE app."{table}" SET {assignments} WHERE {where}'
        pool = await get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(sql, *params)
        modified = int(status.rsplit(" ", 1)[-1]) if status else 0
        return type("UpdateResult", (), {
            "modified_count": modified, "matched_count": modified
        })()

    # Beanie exposes set() as shorthand for an update with $set.
    async def set(self, fields, **kw):
        return await self.update({"$set": dict(fields)}, **kw)

    def __await__(self):
        if self._single:
            return self.first_or_none().__await__()
        return self.to_list().__await__()


class PgCollection:
    """Stands in for the raw pymongo collection a few call sites reach for.

    Only find_one_and_update is implemented, because only the job queue's claim
    needs it. Everything else raises by name rather than returning something
    empty, so a call site that still expects Mongo is found immediately instead
    of quietly reading nothing.
    """

    def __init__(self, model_cls):
        self.model_cls = model_cls

    async def find_one_and_update(self, filter, update, sort=None, **_kw):
        table = table_of(self.model_cls)
        columns = await columns_of(table)
        params: list[Any] = []
        where = _render_filter(dict(filter), params, columns)
        assignments = render_update(dict(update), columns, params)
        order = parse_sort(sort) if sort else ""

        # FOR UPDATE SKIP LOCKED makes the claim atomic across workers: two
        # runners racing take different rows rather than blocking or, worse,
        # both claiming the same job.
        sql = (
            f'UPDATE app."{table}" SET {assignments} WHERE id = ('
            f'  SELECT id FROM app."{table}" WHERE {where}'
            f'{" ORDER BY " + order if order else ""}'
            f'  FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *'
        )
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        return record_to_document(row) if row else None

    async def count_documents(self, filter=None, **_kw) -> int:
        table = table_of(self.model_cls)
        params: list[Any] = []
        where = _render_filter(dict(filter or {}), params, await columns_of(table))
        pool = await get_pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval(
                f'SELECT count(*) FROM app."{table}" WHERE {where}', *params) or 0)

    async def delete_many(self, filter=None, **_kw):
        table = table_of(self.model_cls)
        params: list[Any] = []
        where = _render_filter(dict(filter or {}), params, await columns_of(table))
        pool = await get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f'DELETE FROM app."{table}" WHERE {where}', *params)
        deleted = int(status.rsplit(" ", 1)[-1]) if status else 0
        return type("DeleteResult", (), {"deleted_count": deleted})()

    async def update_many(self, filter, update, **_kw):
        table = table_of(self.model_cls)
        columns = await columns_of(table)
        params: list[Any] = []
        where = _render_filter(dict(filter or {}), params, columns)
        assignments = render_update(dict(update), columns, params)
        pool = await get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f'UPDATE app."{table}" SET {assignments} WHERE {where}', *params)
        modified = int(status.rsplit(" ", 1)[-1]) if status else 0
        return type("UpdateResult", (), {
            "modified_count": modified, "matched_count": modified})()

    async def distinct(self, key, filter=None, **_kw) -> list:
        table = table_of(self.model_cls)
        params: list[Any] = []
        where = _render_filter(dict(filter or {}), params, await columns_of(table))
        column = _map_key(str(key))
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f'SELECT DISTINCT "{column}" AS v FROM app."{table}" '
                f'WHERE {where} AND "{column}" IS NOT NULL', *params)
        return [r["v"] for r in rows]

    def aggregate(self, pipeline, **_kw):
        """Only the pipeline shapes actually used are translated.

        A generic aggregation engine is not the goal; two shapes are, and each
        maps onto something Postgres already does well.
        """
        stages = list(pipeline or [])
        if stages and "$vectorSearch" in stages[0]:
            return _AggregateCursor(self._vector_search(stages))
        if stages and "$match" in stages[0] and any("$group" in s for s in stages):
            return _AggregateCursor(self._match_group(stages))
        raise UnsupportedQuery(
            f"{self.model_cls.__name__}.aggregate() pipeline shape not translated"
        )

    async def _vector_search(self, stages) -> list[dict]:
        """Atlas $vectorSearch -> pgvector KNN.

        `<=>` is cosine distance, so similarity is 1 - distance, matching the
        score Atlas returns. The HNSW index on this column serves the ordering.
        """
        spec = stages[0]["$vectorSearch"]
        table = table_of(self.model_cls)
        column = str(spec.get("path") or "embedding")
        limit = int(spec.get("limit") or 20)
        vector = "[" + ",".join(f"{float(v):.6f}" for v in spec.get("queryVector") or []) + "]"

        projected = {}
        for stage in stages[1:]:
            projected = stage.get("$project") or projected
        fields = [f for f in projected if f not in ("_id", "similarity")] or ["title", "url"]
        selected = ", ".join(f'"{f}"' for f in fields)

        params: list[Any] = [vector]
        where = f'"{column}" IS NOT NULL'
        if spec.get("filter"):
            where += " AND " + _render_filter(
                dict(spec["filter"]), params, await columns_of(table))
        params.append(limit)
        sql = (
            f'SELECT legacy_mongo_id, {selected}, '
            f'1 - ("{column}" <=> $1::vector) AS similarity '
            f'FROM app."{table}" WHERE {where} '
            f'ORDER BY "{column}" <=> $1::vector LIMIT ${len(params)}'
        )
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        out = []
        for row in rows:
            item = {k: row[k] for k in row.keys() if k != "legacy_mongo_id"}
            item["_id"] = row["legacy_mongo_id"]
            out.append(item)
        return out

    async def _match_group(self, stages) -> list[dict]:
        """$match + $group{$sum: 1} -> WHERE + GROUP BY + count(*)."""
        table = table_of(self.model_cls)
        match = stages[0]["$match"]
        group = next(s["$group"] for s in stages if "$group" in s)

        key = group.get("_id")
        if isinstance(key, str):
            keys = {key.lstrip("$"): key.lstrip("$")}
        elif isinstance(key, dict):
            keys = {alias: str(path).lstrip("$") for alias, path in key.items()}
        else:
            raise UnsupportedQuery("$group _id shape not translated")
        for alias, accumulator in group.items():
            if alias == "_id":
                continue
            if accumulator != {"$sum": 1}:
                raise UnsupportedQuery(f"accumulator {accumulator} not translated")

        params: list[Any] = []
        where = _render_filter(dict(match), params, await columns_of(table))
        selected = ", ".join(f'"{_map_key(col)}" AS "{alias}"' for alias, col in keys.items())
        grouped = ", ".join(f'"{_map_key(col)}"' for col in keys.values())
        counters = [a for a in group if a != "_id"]
        counts = ", ".join(f'count(*) AS "{a}"' for a in counters) or 'count(*) AS "count"'
        sql = (
            f'SELECT {selected}, {counts} FROM app."{table}" '
            f"WHERE {where} GROUP BY {grouped}"
        )
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        out = []
        for row in rows:
            record = {"_id": {alias: row[alias] for alias in keys}}
            for counter in counters or ["count"]:
                record[counter] = int(row[counter] or 0)
            out.append(record)
        return out

    def __getattr__(self, name):
        raise UnsupportedQuery(
            f"{self.model_cls.__name__}.{name}() has no Postgres implementation"
        )


class _AggregateCursor:
    """Mongo returns a cursor; call sites do `.aggregate(p).to_list(length=…)`."""

    def __init__(self, coro):
        self._coro = coro

    async def to_list(self, length=None) -> list:
        rows = await self._coro
        return rows[:length] if length else rows

    def __await__(self):
        return self._coro.__await__()


def _render_filter(filter_doc: dict, params: list[Any],
                   columns: dict[str, str] | None = None) -> str:
    from app.db.pg_odm import _render_mongo_dict

    return _render_mongo_dict(filter_doc, params, columns)


def _without_empty_vectors(instance, cols: dict[str, str]) -> dict[str, str]:
    """Drop vector columns the instance has no vector for.

    The embedding pipeline owns `embedding` and writes on its own schedule. A
    scraped record carries an empty one, so including the column here would
    overwrite a perfectly good vector with NULL on every re-scrape - the search
    index would quietly hollow out.
    """
    kept = {}
    for column, data_type in cols.items():
        if is_vector_column(data_type):
            value = getattr(instance, column, None)
            if not value:
                continue
        kept[column] = data_type
    return kept


async def _insert_instance(instance) -> Any:
    from bson import ObjectId

    model_cls = type(instance)
    table = table_of(model_cls)
    cols = {c: t for c, t in (await columns_of(table)).items() if c != "id"}
    # Beanie assigns an id on insert; keep doing so, since call sites read it
    # straight afterwards and downstream rows reference it.
    if getattr(instance, "id", None) is None:
        instance.id = ObjectId()
    cols = _without_empty_vectors(instance, cols)
    values = model_to_values(instance, cols)
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    quoted = ", ".join(f'"{c}"' for c in cols)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            f'INSERT INTO app."{table}" ({quoted}) VALUES ({placeholders}) RETURNING id',
            *values,
        )
    object.__setattr__(instance, "_pg_row_id", row_id)
    return instance


async def _save_instance(instance) -> Any:
    model_cls = type(instance)
    table = table_of(model_cls)
    cols = _without_empty_vectors(
        instance, {c: t for c, t in (await columns_of(table)).items() if c != "id"})
    row_id = getattr(instance, "_pg_row_id", None)
    if row_id is None:
        # Never seen in Postgres: an update to a row that does not exist yet is
        # an insert, which is what Beanie's save() does too.
        return await _insert_instance(instance)
    values = model_to_values(instance, cols)
    assignments = ", ".join(f'"{c}" = ${i+1}' for i, c in enumerate(cols))
    values.append(row_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f'UPDATE app."{table}" SET {assignments} WHERE id = ${len(values)}', *values
        )
    return instance


async def _delete_instance(instance) -> Any:
    table = table_of(type(instance))
    row_id = getattr(instance, "_pg_row_id", None)
    pool = await get_pool()
    async with pool.acquire() as conn:
        if row_id is not None:
            await conn.execute(f'DELETE FROM app."{table}" WHERE id = $1', row_id)
        elif getattr(instance, "id", None) is not None:
            await conn.execute(
                f'DELETE FROM app."{table}" WHERE legacy_mongo_id = $1', str(instance.id)
            )
    return instance


async def _insert_many(model_cls, documents: list) -> Any:
    inserted = [await _insert_instance(d) for d in documents]
    return type("InsertManyResult", (), {
        "inserted_ids": [getattr(d, "id", None) for d in inserted]
    })()


def _attach_fields(model_cls) -> None:
    """Give the class the `Model.field` attributes Beanie would have added.

    Beanie only attaches these during init_beanie, against a live Mongo
    connection. Since the point of this shim is to stop needing that
    connection, the same descriptors are installed here - identically, using
    Beanie's own ExpressionField, so `Model.field == x` and `In(Model.field, xs)`
    build the exact objects the renderer already understands.
    """
    from beanie.odm.fields import ExpressionField

    for name, field in model_cls.model_fields.items():
        if isinstance(getattr(model_cls, name, None), ExpressionField):
            continue  # init_beanie already ran; leave its version alone
        setattr(model_cls, name, ExpressionField(field.alias or name))


def install(models: list) -> int:
    """Point the given models at Postgres.

    Class methods are replaced, not subclassed, so every existing call site
    picks the change up without being touched.
    """
    patched = 0
    for model_cls in models:
        _attach_fields(model_cls)
        # Document.__init__ calls this and discards the result, purely as an
        # initialisation guard, so it has to return something. The adapter also
        # serves the handful of call sites that use the raw collection; those
        # it cannot serve raise by name.
        adapter = PgCollection(model_cls)
        model_cls.get_pymongo_collection = classmethod(lambda cls, _a=adapter: _a)
        model_cls.get_motor_collection = classmethod(lambda cls, _a=adapter: _a)
        def _find_many(*filters, _m=model_cls, **_kw):
            return PgQuery(_m, filters)

        def _find_one(*filters, _m=model_cls, **_kw):
            return PgQuery(_m, filters, single=True)

        def _find_all(_m=model_cls, **_kw):
            return PgQuery(_m, ())

        model_cls.find_many = classmethod(lambda cls, *f, _fn=_find_many, **k: _fn(*f, **k))
        model_cls.find = classmethod(lambda cls, *f, _fn=_find_many, **k: _fn(*f, **k))
        model_cls.find_one = classmethod(lambda cls, *f, _fn=_find_one, **k: _fn(*f, **k))
        model_cls.find_all = classmethod(lambda cls, _fn=_find_all, **k: _fn(**k))
        model_cls.insert = _insert_instance
        model_cls.create = _insert_instance
        model_cls.insert_many = classmethod(
            lambda cls, documents, **k: _insert_many(cls, list(documents))
        )
        model_cls.save = _save_instance
        model_cls.replace = _save_instance
        model_cls.delete = _delete_instance
        patched += 1
    return patched
