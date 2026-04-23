# Security Hardening Final Mile

## 1. Secret Rotation Execution

Local/dev secret rotation:

```bash
python backend/scripts/rotate_local_secrets.py --env-file backend/.env
```

What it does:

- rotates locally managed secrets (`SECRET_KEY`, `JWT_SIGNING_SALT`)
- stamps `SECRETS_LAST_ROTATED_AT`
- creates a timestamped backup by default

Production rotation policy:

- rotate provider-managed credentials (DB, Redis, OAuth, SMTP, LLM) in the secret manager first
- deploy updated runtime secrets
- revoke previous credentials
- run smoke checks for auth, scraper, telemetry, and ask-ai

## 2. Commit-Time and CI Secret Blocking

- Pre-commit hook: `backend/scripts/check_secret_patterns.py`
- CI checks:
  - `.github/workflows/repo-hygiene.yml` (`secret-pattern-check`, `gitleaks`)

## 3. Auth Abuse Lock Policy

Config knobs (`backend/app/core/config.py`):

- `AUTH_ABUSE_MAX_FAILED_ATTEMPTS`
- `AUTH_ABUSE_WINDOW_SECONDS`
- `AUTH_ABUSE_LOCK_SECONDS`

Enforced on:

- password login (`/api/v1/auth/login`)
- OTP verification (`/api/v1/auth/verify-otp`)

## 4. Structured Auth Audit Logs

Collections:

- `auth_audit_events`
- `auth_abuse_states`

Admin APIs:

- `GET /api/v1/auth/audit-events`
- `GET /api/v1/auth/abuse-locks`
