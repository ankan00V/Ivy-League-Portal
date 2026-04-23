#!/usr/bin/env python3
from __future__ import annotations

import argparse
import secrets
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROTATABLE_KEYS: dict[str, int] = {
    "SECRET_KEY": 64,
    "JWT_SIGNING_SALT": 48,
}


def _parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def _render_env(lines: list[str], updates: dict[str, str]) -> str:
    consumed: set[str] = set()
    rendered: list[str] = []

    for raw in lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            rendered.append(raw)
            continue
        key, _ = raw.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in updates:
            rendered.append(f"{normalized_key}={updates[normalized_key]}")
            consumed.add(normalized_key)
        else:
            rendered.append(raw)

    for key, value in updates.items():
        if key in consumed:
            continue
        rendered.append(f"{key}={value}")

    if not rendered:
        for key, value in updates.items():
            rendered.append(f"{key}={value}")

    return "\n".join(rendered) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate locally managed .env secrets.")
    parser.add_argument("--env-file", default="backend/.env", help="Target env file to update.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned updates without writing.")
    parser.add_argument("--no-backup", action="store_true", help="Skip timestamped backup creation.")
    args = parser.parse_args()

    env_path = Path(args.env_file).resolve()
    lines, _existing = _parse_env(env_path)

    updates = {key: secrets.token_urlsafe(length) for key, length in DEFAULT_ROTATABLE_KEYS.items()}
    updates["SECRETS_LAST_ROTATED_AT"] = datetime.now(timezone.utc).isoformat()

    if args.dry_run:
        print(f"[dry-run] would rotate keys in {env_path}: {', '.join(sorted(updates.keys()))}")
        return

    env_path.parent.mkdir(parents=True, exist_ok=True)
    if env_path.exists() and not args.no_backup:
        backup = env_path.with_suffix(f".env.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(env_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"[rotate] backup created: {backup}")

    rendered = _render_env(lines, updates)
    env_path.write_text(rendered, encoding="utf-8")
    print(f"[rotate] rotated keys in {env_path}: {', '.join(sorted(updates.keys()))}")


if __name__ == "__main__":
    main()
