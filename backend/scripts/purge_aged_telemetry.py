#!/usr/bin/env python3
"""Unlink behavioural telemetry older than the retention window from its students.

`opportunity_interactions` had no retention policy at all: every impression, dwell
time, scroll depth and typed search query stayed attached to a named student
indefinitely. `auth_audit_events` and `otp_codes` already had TTL indexes; the
collection that records what people actually looked at did not.

This does **not** delete rows. It replaces `user_id` with a derived pseudonym and
clears the free-text `query`, so every count, funnel and experiment denominator
computed over history stays exactly the same while the rows stop pointing at a
person. Deleting them instead would silently shrink historical impression counts —
the precise failure this repo has already been bitten by twice (see
`app/models/traffic.py`).

Dry run by default. Nothing is written unless `--apply` is passed.

    ./backend/venv/bin/python backend/scripts/purge_aged_telemetry.py
    ./backend/venv/bin/python backend/scripts/purge_aged_telemetry.py --apply

The window is `TELEMETRY_RAW_RETENTION_DAYS` (default 400 days). Set it to 0 to
disable retention, in which case this script reports "disabled" and exits without
touching anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap import init_database  # noqa: E402
from app.services.telemetry_privacy import purge_aged_telemetry  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite the aged rows. Without this flag the script only reports.",
    )
    args = parser.parse_args()

    client = await init_database()
    try:
        report = await purge_aged_telemetry(apply=args.apply)
        print(json.dumps(report, indent=2))
        if report.get("status") == "disabled":
            print(
                "\nRetention is disabled (TELEMETRY_RAW_RETENTION_DAYS <= 0).",
                file=sys.stderr,
            )
        elif not args.apply:
            print("\nDry run. Re-run with --apply to rewrite these rows.", file=sys.stderr)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
