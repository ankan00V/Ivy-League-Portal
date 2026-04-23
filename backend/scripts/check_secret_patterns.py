#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

# Mark intentionally safe lines with this token to bypass scanning.
ALLOW_MARKER = "secret-scan: allow"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_project_key", re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("nvidia_api_key", re.compile(r"nvapi-[A-Za-z0-9_-]{20,}")),
    ("github_pat", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("mongo_uri_with_password", re.compile(r"mongodb\+srv://[^:@/\s]+:[^@/\s]+@")),
    ("redis_uri_with_password", re.compile(r"rediss?://[^:@/\s]+:[^@/\s]+@")),
    ("upstash_rest_token_assignment", re.compile(r"UPSTASH_REDIS_REST_TOKEN\s*=\s*['\"]?[A-Za-z0-9_-]{20,}")),
]

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".lock",
}

SKIP_PARTS = {
    "/.git/",
    "/backend/venv/",
    "/frontend/node_modules/",
    "/frontend/.next/",
    "/__pycache__/",
}


def _git_tracked_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    raw = proc.stdout.decode("utf-8", errors="ignore")
    entries = [entry for entry in raw.split("\x00") if entry]
    return [REPO_ROOT / entry for entry in entries]


def _normalize_paths(paths: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    for value in paths:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.is_file():
            resolved.append(candidate)
    return resolved


def _is_scannable(path: Path) -> bool:
    posix = path.as_posix()
    if any(part in posix for part in SKIP_PARTS):
        return False
    if path.name.startswith(".env"):
        return False
    if path.name.endswith(".example"):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return True


def _looks_like_placeholder(line: str) -> bool:
    lowered = line.lower()
    placeholder_tokens = [
        "example",
        "placeholder",
        "replace",
        "dummy",
        "<password>",
        "<your-",
    ]
    return any(token in lowered for token in placeholder_tokens)


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for name, pattern in SECRET_PATTERNS:
            if not pattern.search(line):
                continue
            if _looks_like_placeholder(line):
                continue
            findings.append((line_number, name, line.strip()))
    return findings


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fail when high-risk secret patterns are found.")
    parser.add_argument("paths", nargs="*", help="Optional file paths. Defaults to all tracked files.")
    args = parser.parse_args(argv)

    candidate_paths = _normalize_paths(args.paths) if args.paths else _git_tracked_files()
    violations: list[tuple[Path, int, str, str]] = []

    for path in candidate_paths:
        if not path.is_file() or not _is_scannable(path):
            continue
        for line_no, kind, content in _scan_file(path):
            violations.append((path, line_no, kind, content))

    if not violations:
        print("secret-pattern-check: no findings")
        return 0

    print("secret-pattern-check: potential secret(s) found:")
    for path, line_no, kind, content in violations:
        relative = path.relative_to(REPO_ROOT)
        print(f"- {relative}:{line_no} [{kind}] {content[:200]}")
    print("\nMove credentials to .env (untracked) and retry.")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
