#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _bool_value(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").strip().lower() == "true"


def _int_value(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(values.get(key, default))
    except Exception:
        return default


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _contains(path: Path, needles: Iterable[str], failures: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for needle in needles:
        _require(needle in text, f"{path.relative_to(REPO_ROOT)} must contain: {needle}", failures)


def _check_env_contracts(failures: list[str]) -> None:
    production = _parse_env(REPO_ROOT / "backend/.env.production.example")
    local_example = _parse_env(REPO_ROOT / "backend/.env.example")
    local_env_path = REPO_ROOT / "backend/.env"
    local_env = _parse_env(local_env_path)

    required_keys = [
        "AUTH_SESSION_STORE_ENABLED",
        "AUTH_SESSION_REQUIRE_SERVER_STATE",
        "AUTH_SESSION_BIND_DEVICE",
        "AUTH_SESSION_REDIS_PREFIX",
        "AUTH_SESSION_ACTIVITY_UPDATE_INTERVAL_SECONDS",
        "CSRF_DOUBLE_SUBMIT_ENABLED",
        "CSRF_COOKIE_NAME",
        "CSRF_HEADER_NAME",
        "JOBS_MAX_CONCURRENCY",
        "JOBS_HANDLER_TIMEOUT_SECONDS",
        "JOBS_MAX_PENDING_PER_TYPE",
        "DISCOVERY_ENABLED",
        "SERPAPI_KEY",
        "GOOGLE_SEARCH_API_KEY",
        "CLAUDE_API_KEY",
        "CLAUDE_MODEL",
        "MAX_LLM_EXTRACTIONS_PER_HOUR",
        "MONTHLY_LLM_BUDGET_USD",
        "ADMIN_WEBHOOK_URL",
        "QUALIFICATION_MIN_SCORE",
        "TRUST_MIN_SCORE_AUTO_PROMOTE",
        "TRUST_MIN_SCORE_REQUIRE_REVIEW",
        "PROBATION_MIN_RUNS",
        "PROBATION_MIN_PARSE_RATE",
        "PROBATION_DAYS",
        "SOURCE_FETCH_RATE_LIMIT",
        "SOURCE_DISCOVERY_MAX_CONCURRENT",
        "SOURCE_SUBMISSION_DAILY_LIMIT",
    ]
    for key in required_keys:
        _require(key in production, f"backend/.env.production.example missing {key}", failures)
        _require(key in local_example, f"backend/.env.example missing {key}", failures)
        if local_env_path.exists():
            _require(key in local_env, f"backend/.env missing {key}", failures)

    for key in [
        "AUTH_SESSION_COOKIE_ENABLED",
        "AUTH_SESSION_COOKIE_SECURE",
        "AUTH_SESSION_STORE_ENABLED",
        "AUTH_SESSION_REQUIRE_SERVER_STATE",
        "AUTH_SESSION_BIND_DEVICE",
        "AUTH_COOKIE_ONLY_MODE",
        "CSRF_PROTECTION_ENABLED",
        "CSRF_ENFORCE_ON_AUTH_COOKIE",
        "CSRF_DOUBLE_SUBMIT_ENABLED",
        "RATE_LIMIT_ENABLED",
        "JOBS_ENABLED",
        "DISCOVERY_ENABLED",
    ]:
        _require(_bool_value(production, key), f"production env must set {key}=true", failures)

    _require(production.get("CSRF_COOKIE_NAME") == "vidyaverse_csrf", "production CSRF_COOKIE_NAME must be stable", failures)
    _require(production.get("CSRF_HEADER_NAME") == "X-CSRF-Token", "production CSRF_HEADER_NAME must be stable", failures)
    _require(_int_value(production, "ADMIN_SESSION_MAX_AGE_SECONDS") <= 14_400, "admin session TTL must be <= 4 hours", failures)
    _require(
        _int_value(production, "RATE_LIMIT_ADMIN_REQUESTS_PER_MINUTE") <= 30,
        "admin rate limit should remain conservative",
        failures,
    )
    _require(
        _int_value(production, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE") <= 30,
        "auth rate limit should remain conservative",
        failures,
    )
    _require(_int_value(production, "JOBS_MAX_CONCURRENCY") >= 2, "production job concurrency should be at least 2", failures)
    _require(
        _int_value(production, "JOBS_HANDLER_TIMEOUT_SECONDS") <= 1800,
        "job handler timeout should be bounded to <= 30 minutes",
        failures,
    )
    _require(
        _int_value(production, "JOBS_MAX_PENDING_PER_TYPE") > 0,
        "per-type job queue cap must be enabled",
        failures,
    )
    _require(
        _int_value(production, "MAX_LLM_EXTRACTIONS_PER_HOUR") <= 10,
        "LLM extraction hourly cap should remain conservative",
        failures,
    )
    _require(
        float(production.get("MONTHLY_LLM_BUDGET_USD") or 0) > 0,
        "monthly LLM source-discovery budget must be configured",
        failures,
    )
    _require(
        float(production.get("QUALIFICATION_MIN_SCORE") or 0) >= 60,
        "source qualification threshold must remain >= 60",
        failures,
    )
    _require(
        float(production.get("TRUST_MIN_SCORE_AUTO_PROMOTE") or 0) >= 70,
        "auto-promotion trust threshold must remain >= 70",
        failures,
    )
    _require(
        _int_value(production, "PROBATION_MIN_RUNS") >= 3,
        "source probation must require at least 3 runs",
        failures,
    )
    _require(
        float(production.get("PROBATION_MIN_PARSE_RATE") or 0) >= 0.70,
        "source probation parse-rate threshold must remain >= 0.70",
        failures,
    )


def _check_workflow_contracts(failures: list[str]) -> None:
    _contains(
        REPO_ROOT / ".github/workflows/pr-quality-gate.yml",
        [
            "python -m pytest -q backend/tests",
            "python backend/scripts/check_release_contracts.py",
            "npm run lint",
            "npm run build",
        ],
        failures,
    )
    _contains(
        REPO_ROOT / ".github/workflows/production-readiness-gate.yml",
        [
            "python backend/scripts/check_release_contracts.py",
            "backend.tests.test_session_security_service",
            "backend.tests.test_parser_contract",
            "backend.tests.test_opportunity_quality_service",
            "backend.tests.test_duplicate_detector",
            "backend.tests.test_ranker_feature_builder",
            "backend.tests.test_cold_start_service",
            "backend.tests.test_job_runner_scaling",
            "backend.tests.test_bootstrap_demo_data",
            "backend.tests.test_cache_manager",
            "backend.tests.test_data_bootstrap_scripts",
            "backend.tests.test_source_discovery_pipeline",
        ],
        failures,
    )
    _contains(
        REPO_ROOT / ".github/workflows/release-blocking-ml-gates.yml",
        [
            "check_real_traffic_rollout_readiness.py",
            "check_champion_challenger_gate.py",
            "check_ds_release_gates.py",
            "run_assistant_quality_eval.py",
        ],
        failures,
    )
    _contains(
        REPO_ROOT / "Makefile",
        [
            "release-contracts:",
            "check_release_contracts.py",
            "bootstrap-demo-data:",
            "bootstrap_demo_data.py",
            "bootstrap-opportunities:",
            "bootstrap_opportunities.py",
            "seed-test-data:",
            "seed_test_data.py",
            "validate-data-health:",
            "validate_data_health.py",
            "dataset-snapshot:",
            "export_dataset_snapshot.py",
            "bootstrap_company_seeds.py",
        ],
        failures,
    )
    for script in [
        "bootstrap_opportunities.py",
        "seed_test_data.py",
        "validate_data_health.py",
        "export_dataset_snapshot.py",
        "bootstrap_company_seeds.py",
    ]:
        _require((REPO_ROOT / "backend/scripts" / script).is_file(), f"backend/scripts/{script} is required", failures)
    for path in [
        "backend/app/models/source_discovery.py",
        "backend/app/services/source_discovery.py",
        "backend/app/api/api_v1/endpoints/source_discovery_admin.py",
        "backend/app/api/api_v1/endpoints/sources.py",
        "docs/runbooks/source-discovery-pipeline.md",
    ]:
        _require((REPO_ROOT / path).is_file(), f"{path} is required", failures)
    _contains(
        REPO_ROOT / "backend/app/services/job_runner.py",
        [
            "source_discovery_run",
            "source_qualification_batch",
            "source_extraction_batch",
            "probation_scrape_run",
            "source_health_monitor",
            "company_seed_careers_finder",
            "trust_score_recompute",
        ],
        failures,
    )
    _contains(
        REPO_ROOT / "backend/app/core/metrics.py",
        [
            "discovery_sources_discovered_total",
            "discovery_sources_promoted_total",
            "discovery_sources_in_pipeline",
            "discovery_llm_calls_total",
            "discovery_llm_cost_usd_total",
            "discovery_probation_sources",
        ],
        failures,
    )
    _contains(
        REPO_ROOT / "backend/app/api/api_v1/api.py",
        [
            'prefix="/sources"',
            'prefix="/admin/discovery"',
            'prefix="/admin/seeds"',
            'prefix="/admin/sources"',
        ],
        failures,
    )
    _contains(
        REPO_ROOT / "docs/runbooks/production-release-closure.md",
        [
            "make bootstrap-opportunities",
            "make validate-data-health",
            "AUTH_SESSION_REQUIRE_SERVER_STATE=true",
            "source-discovery-pipeline.md",
        ],
        failures,
    )


def main() -> int:
    failures: list[str] = []
    _check_env_contracts(failures)
    _check_workflow_contracts(failures)
    if failures:
        print("release-contract-check: failed")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("release-contract-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
