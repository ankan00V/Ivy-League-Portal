#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required. Install GitHub CLI first." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

REPO="${1:-${GITHUB_REPOSITORY:-}}"
if [ -z "${REPO}" ]; then
  echo "Usage: $0 <owner/repo>  (or set GITHUB_REPOSITORY)" >&2
  exit 1
fi

required_keys=(
  STAGING_PLAYWRIGHT_BASE_URL
  STAGING_PLAYWRIGHT_ADMIN_EMAIL
  STAGING_PLAYWRIGHT_ADMIN_PASSWORD
  STAGING_PLAYWRIGHT_EMPLOYER_EMAIL
  STAGING_PLAYWRIGHT_EMPLOYER_PASSWORD
  MLOPS_ALERT_SLACK_WEBHOOK_URL
  MLOPS_ALERT_PAGERDUTY_ROUTING_KEY
  MLOPS_INCIDENT_DEFAULT_OWNER
  MLOPS_ONCALL_PRIMARY
  MLOPS_ONCALL_SECONDARY
)

for key in "${required_keys[@]}"; do
  if [ -z "${!key:-}" ]; then
    echo "Missing required env var: ${key}" >&2
    exit 1
  fi
done

echo "[ops] configuring GitHub secrets for ${REPO}"
gh secret set STAGING_PLAYWRIGHT_BASE_URL --repo "${REPO}" --body "${STAGING_PLAYWRIGHT_BASE_URL}"
gh secret set STAGING_PLAYWRIGHT_ADMIN_EMAIL --repo "${REPO}" --body "${STAGING_PLAYWRIGHT_ADMIN_EMAIL}"
gh secret set STAGING_PLAYWRIGHT_ADMIN_PASSWORD --repo "${REPO}" --body "${STAGING_PLAYWRIGHT_ADMIN_PASSWORD}"
gh secret set STAGING_PLAYWRIGHT_EMPLOYER_EMAIL --repo "${REPO}" --body "${STAGING_PLAYWRIGHT_EMPLOYER_EMAIL}"
gh secret set STAGING_PLAYWRIGHT_EMPLOYER_PASSWORD --repo "${REPO}" --body "${STAGING_PLAYWRIGHT_EMPLOYER_PASSWORD}"
gh secret set MLOPS_ALERT_SLACK_WEBHOOK_URL --repo "${REPO}" --body "${MLOPS_ALERT_SLACK_WEBHOOK_URL}"
gh secret set MLOPS_ALERT_PAGERDUTY_ROUTING_KEY --repo "${REPO}" --body "${MLOPS_ALERT_PAGERDUTY_ROUTING_KEY}"
gh variable set MLOPS_INCIDENT_DEFAULT_OWNER --repo "${REPO}" --body "${MLOPS_INCIDENT_DEFAULT_OWNER}"
gh variable set MLOPS_ONCALL_PRIMARY --repo "${REPO}" --body "${MLOPS_ONCALL_PRIMARY}"
gh variable set MLOPS_ONCALL_SECONDARY --repo "${REPO}" --body "${MLOPS_ONCALL_SECONDARY}"

echo "[ops] secrets/vars configured"
