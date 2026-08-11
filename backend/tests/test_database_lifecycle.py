"""`init_database()` can return None, and every caller has to survive that.

`POSTGRES_ODM_ENABLED` makes `init_database()` patch the document models onto
Postgres and return **None** — there is no Mongo client to hand back because Mongo
was never contacted. That is the honest return value, but it silently changed the
contract of a function whose result eight call sites were closing unconditionally.

The result was a trap armed for exactly the moment the flag is turned on: the API
shutdown path and the background worker would both raise

    AttributeError: 'NoneType' object has no attribute 'close'

on the way out. Nothing catches it today because the flag defaults to off, so the
whole thing is invisible until the cutover — the worst possible time to find it.

This sweeps the callers rather than trusting a one-time fix, because the next
script anyone writes will copy the unguarded pattern from a neighbour.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: `bootstrap.py` defines init_database. Its own `client.close()` belongs to the
#: retry loop in `connect_mongo_with_retries`, where the client is always real,
#: so it is not part of this contract.
_EXEMPT = {"app/bootstrap.py"}


def _callers() -> list[Path]:
    found: list[Path] = []
    for root in ("app", "scripts"):
        for path in (BACKEND_ROOT / root).rglob("*.py"):
            rel = path.relative_to(BACKEND_ROOT).as_posix()
            if rel in _EXEMPT or "venv" in rel:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\binit_database\s*\(\s*\)", text):
                found.append(path)
    return sorted(found)


class TestInitDatabaseCallers:
    def test_callers_are_discovered(self):
        """Guard against the sweep silently matching nothing."""
        assert len(_callers()) >= 5

    @pytest.mark.parametrize("path", _callers(), ids=lambda p: p.name)
    def test_every_caller_guards_against_a_none_client(self, path: Path):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "client.close()" not in text:
            pytest.skip("does not close the client")
        assert "if client is not None" in text, (
            f"{path.relative_to(BACKEND_ROOT)} closes the init_database() client without "
            "checking for None. Under POSTGRES_ODM_ENABLED that call returns None and "
            "this raises AttributeError on shutdown."
        )

    def test_init_database_declares_it_can_return_none(self):
        """The signature has to advertise the contract the callers guard for."""
        source = (BACKEND_ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
        match = re.search(r"async def init_database\(\)\s*->\s*([^:]+):", source)
        assert match, "init_database signature not found"
        assert "Optional" in match.group(1) or "None" in match.group(1), (
            "init_database can return None under POSTGRES_ODM_ENABLED; its return "
            "annotation must say so, or callers have no reason to guard."
        )


class TestShutdownPaths:
    """The two that actually matter in production."""

    @pytest.mark.parametrize("rel", ["app/main.py", "app/worker.py"])
    def test_runtime_shutdown_tolerates_a_none_client(self, rel: str):
        text = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
        close_at = text.index("client.close()")
        window = text[max(0, close_at - 400) : close_at]
        assert "if client is not None" in window, (
            f"{rel} must not close a possibly-None Mongo client during shutdown."
        )
