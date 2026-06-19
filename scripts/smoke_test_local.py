from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class SmokeResult:
    name: str
    passed: bool
    detail: str
    critical: bool = True


def _get_json(url: str, *, timeout: float) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else None
            return int(response.status), payload, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = None
        return int(exc.code), payload, raw[:300]
    except Exception as exc:
        return 0, None, f"{exc.__class__.__name__}: {exc}"


def _get_status(url: str, *, timeout: float) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), ""
    except Exception as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def run_smoke(
    *,
    backend_url: str,
    frontend_url: str,
    timeout: float,
    require_artifact_store: bool,
    require_warehouse_fresh: bool,
) -> list[SmokeResult]:
    backend = backend_url.rstrip("/")
    frontend = frontend_url.rstrip("/")
    results: list[SmokeResult] = []

    status, health, error = _get_json(f"{backend}/health", timeout=timeout)
    health_payload = health if isinstance(health, dict) else {}
    service_name = str(health_payload.get("service") or "")
    results.append(
        SmokeResult(
            "backend /health identifies VidyaVerse",
            status == 200 and isinstance(health, dict) and service_name == "VidyaVerse API",
            f"status={status}, service={service_name or 'missing'} {error}".strip(),
        )
    )

    checks = dict(health_payload.get("checks") or {})
    operational = dict(health_payload.get("operational") or {})
    embedding = dict(health_payload.get("embedding") or {})
    warehouse = dict(health_payload.get("warehouse") or {})

    for key in ("mongodb", "redis", "queue"):
        component = dict(checks.get(key) or {})
        results.append(
            SmokeResult(
                f"{key} healthy",
                bool(component.get("ok")),
                str(component.get("detail") or "missing"),
            )
        )

    results.append(
        SmokeResult(
            "embedding model ready",
            not bool(embedding.get("degraded")),
            f"provider={embedding.get('provider') or 'unknown'}, degraded={embedding.get('degraded')}",
        )
    )
    results.append(
        SmokeResult(
            "learned ranker ready",
            bool(operational.get("learned_ranker_ready")),
            f"learned_ranker_ready={operational.get('learned_ranker_ready')}",
        )
    )

    artifact = dict(checks.get("artifact_store") or {})
    results.append(
        SmokeResult(
            "artifact store accessible",
            bool(artifact.get("ok")),
            str(artifact.get("detail") or "missing"),
            critical=require_artifact_store,
        )
    )

    freshness = dict(warehouse.get("freshness") or {})
    results.append(
        SmokeResult(
            "warehouse freshness",
            bool(freshness.get("fresh")),
            f"status={freshness.get('status') or 'unknown'}",
            critical=require_warehouse_fresh,
        )
    )

    status, opportunities, error = _get_json(f"{backend}/api/v1/opportunities/?limit=5", timeout=timeout)
    if isinstance(opportunities, list):
        count = len(opportunities)
    elif isinstance(opportunities, dict):
        count = len(opportunities.get("items") or opportunities.get("results") or opportunities.get("opportunities") or [])
    else:
        count = 0
    results.append(
        SmokeResult(
            "public opportunities return data",
            status == 200 and count > 0,
            f"status={status}, count={count} {error}".strip(),
        )
    )

    status, _ = _get_status(f"{backend}/docs", timeout=timeout)
    results.append(SmokeResult("API docs reachable", status == 200, f"status={status}", critical=False))

    for path in ("/", "/dashboard", "/login", "/opportunities", "/internships-jobs"):
        status, error = _get_status(f"{frontend}{path}", timeout=timeout)
        results.append(
            SmokeResult(
                f"frontend {path}",
                status == 200,
                f"status={status} {error}".strip(),
            )
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a local VidyaVerse stack.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8010")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3002")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--require-artifact-store", action="store_true")
    parser.add_argument("--require-warehouse-fresh", action="store_true")
    args = parser.parse_args()

    results = run_smoke(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        timeout=max(1.0, args.timeout),
        require_artifact_store=bool(args.require_artifact_store),
        require_warehouse_fresh=bool(args.require_warehouse_fresh),
    )
    passed = sum(1 for item in results if item.passed)
    print(f"Smoke test: {passed}/{len(results)} checks passed")
    for item in results:
        marker = "PASS" if item.passed else "WARN" if not item.critical else "FAIL"
        print(f"[{marker}] {item.name}: {item.detail}")

    critical_failures = [item for item in results if item.critical and not item.passed]
    if critical_failures:
        print(f"Smoke test failed: {len(critical_failures)} critical check(s) failed.", file=sys.stderr)
        return 1
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
