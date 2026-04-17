from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUSPICIOUS_SUFFIX = re.compile(r"(?:\s+\d+| copy|\(\d+\))$", re.IGNORECASE)
ALLOWED_DIRS = {".git", "node_modules", ".next", "__pycache__"}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ALLOWED_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def main() -> int:
    suspicious: list[Path] = []
    for path in _iter_files():
        if SUSPICIOUS_SUFFIX.search(path.stem):
            suspicious.append(path)

    if not suspicious:
        print("No duplicate artifact filenames detected.")
        return 0

    print("Duplicate artifact-style filenames detected:", file=sys.stderr)
    for path in sorted(suspicious):
        print(f" - {path.relative_to(ROOT)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
