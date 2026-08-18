"""Test setup.

`scripts/` is not a package and is normally run as `python scripts/foo.py`, which
puts that directory on sys.path implicitly. Tests import from it (notably
`_script_db`), so the same path is added here rather than in each test.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for candidate in (BACKEND_ROOT, BACKEND_ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
