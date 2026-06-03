#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.publish_dataset_snapshot import _main


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
