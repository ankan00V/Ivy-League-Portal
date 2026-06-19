from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    severity: str
    detail: str


def _value(name: str) -> object:
    if name in os.environ:
        return os.environ.get(name)
    return getattr(settings, name, None)


def _has_value(name: str) -> bool:
    return bool(str(_value(name) or "").strip())


def _masked_presence(name: str) -> str:
    return "set" if _has_value(name) else "missing"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(_value(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _check_required(name: str, *, severity: str = "fatal") -> CheckResult:
    return CheckResult(
        name=name,
        ok=_has_value(name),
        severity=severity,
        detail=_masked_presence(name),
    )


def _validate_llm() -> list[CheckResult]:
    provider = str(_value("LLM_PROVIDER") or "openai_compatible").strip().lower()
    results = [
        CheckResult(
            name="LLM_PROVIDER",
            ok=provider in {"openai_compatible", "bedrock"},
            severity="fatal",
            detail=provider or "missing",
        )
    ]
    if provider == "bedrock":
        results.append(_check_required("AWS_BEARER_TOKEN_BEDROCK"))
        results.append(_check_required("BEDROCK_MODEL_ID", severity="warning"))
        return results

    has_generic_key = _has_value("LLM_API_KEY")
    has_openrouter_key = _has_value("OPENROUTER_API_KEY")
    results.append(
        CheckResult(
            name="LLM_API_KEY or OPENROUTER_API_KEY",
            ok=has_generic_key or has_openrouter_key,
            severity="fatal",
            detail=f"LLM_API_KEY={_masked_presence('LLM_API_KEY')}, "
            f"OPENROUTER_API_KEY={_masked_presence('OPENROUTER_API_KEY')}",
        )
    )
    results.append(_check_required("LLM_MODEL", severity="warning"))
    results.append(_check_required("LLM_API_BASE_URL", severity="warning"))
    return results


def validate(*, production: bool = False) -> list[CheckResult]:
    results = [
        _check_required("MONGODB_URL"),
        _check_required("REDIS_URL"),
        _check_required("SECRET_KEY"),
        CheckResult(
            name="SECRET_KEY is not default",
            ok=not str(_value("SECRET_KEY") or "").startswith("your_super_secret_key_here"),
            severity="fatal" if production else "warning",
            detail="default development key"
            if str(_value("SECRET_KEY") or "").startswith("your_super_secret_key_here")
            else "custom key",
        ),
        CheckResult(
            name="ClickHouse startup mode",
            ok=True,
            severity="info",
            detail="enabled" if _bool_env("ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED") else "disabled",
        ),
        CheckResult(
            name="Artifact store endpoint",
            ok=True,
            severity="info",
            detail=_masked_presence("MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL"),
        ),
        CheckResult(
            name="Turnstile",
            ok=not production or (_bool_env("TURNSTILE_ENABLED") and _has_value("TURNSTILE_SECRET_KEY")),
            severity="fatal" if production else "info",
            detail="enabled" if _bool_env("TURNSTILE_ENABLED") else "disabled",
        ),
    ]
    results.extend(_validate_llm())
    return results


def _print_results(results: Iterable[CheckResult]) -> None:
    for result in results:
        label = "ok" if result.ok else result.severity
        print(f"[{label}] {result.name}: {result.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate VidyaVerse backend runtime environment.")
    parser.add_argument("--production", action="store_true", help="Treat production-only warnings as fatal.")
    args = parser.parse_args()

    results = validate(production=bool(args.production))
    _print_results(results)
    fatal_failures = [item for item in results if not item.ok and item.severity == "fatal"]
    if fatal_failures:
        print(f"ENV validation failed: {len(fatal_failures)} fatal issue(s).", file=sys.stderr)
        return 1
    print("ENV validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
