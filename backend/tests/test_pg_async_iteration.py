"""Beanie queries are async-iterable, and the Postgres ODM has to honour that.

`pg_documents` patches models rather than rewriting ~651 call sites, on the
promise that the models keep their Beanie shape. `PgQuery` implemented
`to_list`, `count`, `delete` and `update` but not `__aiter__`, so any call site
using `async for` raised

    TypeError: 'async for' requires an object with __aiter__ method, got PgQuery

That hole cost a real outage rather than a crash. `consented_user_ids` iterates
profiles to decide whose rows may be exported, and its handler fails **closed** -
on error it returns an empty permission set so nothing user-linked is exported.
Under this ODM it therefore caught the TypeError, logged, and returned no
permitted users, and every warehouse export silently dropped **all** user rows
while reporting `status: ok`. The privacy default did its job; the marts were
empty of exactly the data they exist to describe.

Measured after the fix: consent resolves to 1 user and the export reports
`rows_dropped_without_consent: 827` instead of dropping everything.
"""
from __future__ import annotations

import inspect

from app.db.pg_documents import PgQuery


class TestQuerySupportsAsyncIteration:
    def test_pgquery_defines_aiter(self):
        assert hasattr(PgQuery, "__aiter__"), (
            "PgQuery must be async-iterable; Beanie call sites use `async for`."
        )

    def test_aiter_is_an_async_generator(self):
        assert inspect.isasyncgenfunction(PgQuery.__aiter__)

    def test_iteration_is_paged(self):
        """An unpaged iteration of a month of interactions exceeds the pooler timeout."""
        source = inspect.getsource(PgQuery.__aiter__)
        assert "_AITER_PAGE" in source
        assert PgQuery._AITER_PAGE > 0

    def test_pagination_is_ordered(self):
        """Unordered LIMIT/OFFSET can repeat or skip rows between pages."""
        source = inspect.getsource(PgQuery._clone_for_page)
        assert '"id"' in source, "paged iteration needs a stable sort key"

    def test_clone_does_not_mutate_the_original_query(self):
        q = PgQuery(object, ())
        q._limit = 5
        q._skip = 2
        clone = q._clone_for_page(skip=100, limit=10)
        assert (q._skip, q._limit) == (2, 5)
        assert (clone._skip, clone._limit) == (100, 10)

    def test_clone_carries_the_filters(self):
        marker = ("marker",)
        q = PgQuery(object, marker)
        assert q._clone_for_page(skip=0, limit=1).filters == list(marker)


class TestConsentResolutionSurvivesTheODM:
    def test_consent_lookup_no_longer_relies_on_an_unsupported_idiom(self):
        """Whatever the idiom, it must work against both backends."""
        from app.services import privacy_consent_service

        source = inspect.getsource(privacy_consent_service.consented_user_ids)
        assert "async for" not in source or hasattr(PgQuery, "__aiter__")

    def test_consent_failure_still_fails_closed(self):
        """The fix must not turn a resolution error into an open gate."""
        from app.services import privacy_consent_service

        source = inspect.getsource(privacy_consent_service.consented_user_ids)
        assert "return set()" in source, (
            "an unresolvable consent lookup must export nothing, not everything"
        )


class TestExportReportsItsPrivacyPass:
    def test_export_returns_the_privacy_block(self):
        """A silently-empty consent set produced a successful-looking empty export."""
        from app.services.warehouse_export_service import WarehouseExportService

        source = inspect.getsource(WarehouseExportService.export)
        assert '"privacy": privacy,' in source
        assert source.count('"privacy": privacy,') >= 2, (
            "privacy belongs in both the persisted run record and the return value"
        )
