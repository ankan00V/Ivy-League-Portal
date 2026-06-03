# Production Release Closure Runbook

This runbook closes the June 2026 production-readiness phases for VidyaVerse.

## Mandatory Local Gates

```bash
backend/venv/bin/python -m pytest -q backend/tests
npm run lint --prefix frontend
npm run build --prefix frontend
backend/venv/bin/python backend/scripts/check_secret_patterns.py
backend/venv/bin/python backend/scripts/check_duplicate_artifacts.py
backend/venv/bin/python backend/scripts/check_release_contracts.py
git diff --check
```

## Data Bootstrap

```bash
make bootstrap-opportunities
make seed-test-data
make validate-data-health
make dataset-snapshot
```

Use `seed-test-data` only for local, CI, staging, or demo environments. It creates synthetic users, employers, experiments, and interaction signal.

## Source Discovery

Before enabling autonomous source growth, review `docs/runbooks/source-discovery-pipeline.md` and confirm discovery budgets, admin review ownership, and webhook routing.

## Security Gates

Production must keep these true:

- `AUTH_SESSION_STORE_ENABLED=true`
- `AUTH_SESSION_REQUIRE_SERVER_STATE=true`
- `AUTH_SESSION_BIND_DEVICE=true`
- `AUTH_SESSION_COOKIE_SECURE=true`
- `AUTH_COOKIE_ONLY_MODE=true`
- `CSRF_PROTECTION_ENABLED=true`
- `CSRF_ENFORCE_ON_AUTH_COOKIE=true`
- `CSRF_DOUBLE_SUBMIT_ENABLED=true`

Run `make release-contracts` after env template or workflow changes.

## Queue and Cache Controls

Background job settings:

- `JOBS_MAX_CONCURRENCY`
- `JOBS_HANDLER_TIMEOUT_SECONDS`
- `JOBS_MAX_PENDING_PER_TYPE`

Cache invalidation is best-effort Redis-backed and currently wired for:

- profile, onboarding, and resume updates
- user interaction writes
- opportunity-change helper hooks
- model-update pubsub through `channel:model_update`

## Release Evidence

Attach these outputs to release notes:

- backend pytest count
- frontend lint/build status
- release-contract result
- data-health report
- dataset snapshot JSON path
- production infra readiness report when managed secrets are configured
