#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -n "${COMPOSE:-}" ]]; then
  read -r -a COMPOSE_CMD <<< "${COMPOSE}"
else
  COMPOSE_CMD=(docker compose)
fi

compose() {
  "${COMPOSE_CMD[@]}" "$@"
}

checks_passed=0
checks_failed=0

mark_ok() {
  checks_passed=$((checks_passed + 1))
  printf '[ok] %s\n' "$1"
}

mark_fail() {
  checks_failed=$((checks_failed + 1))
  printf '[fail] %s\n' "$1" >&2
}

wait_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay="${4:-2}"

  for _ in $(seq 1 "${attempts}"); do
    if python3 - "${url}" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    if 200 <= int(response.status) < 500:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
      mark_ok "${name} reachable at ${url}"
      return 0
    fi
    sleep "${delay}"
  done
  mark_fail "${name} not reachable at ${url}"
  return 1
}

run_check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    mark_ok "${name}"
  else
    mark_fail "${name}"
    return 1
  fi
}

main() {
  run_check "docker compose config" compose config

  wait_http "backend health" "${BACKEND_HEALTH_URL:-http://localhost:8000/health}" 90 2
  wait_http "prometheus readiness" "${PROMETHEUS_READY_URL:-http://localhost:9090/-/ready}" 60 2
  wait_http "grafana health" "${GRAFANA_HEALTH_URL:-http://localhost:3001/api/health}" 60 2
  wait_http "minio health" "${MINIO_HEALTH_URL:-http://localhost:9002/minio/health/ready}" 60 2
  wait_http "clickhouse ping" "${CLICKHOUSE_PING_URL:-http://localhost:8123/ping}" 60 2

  run_check "mongo replica set health" compose exec -T mongo mongosh --quiet \
    -u "${MONGO_INITDB_ROOT_USERNAME:-vidyaverse}" \
    -p "${MONGO_INITDB_ROOT_PASSWORD:-vidyaverse-dev-password}" \
    --authenticationDatabase admin \
    --eval "rs.status().ok"

  run_check "redis ping" compose exec -T redis redis-cli ping

  if [[ -f backend/warehouse/clickhouse_schema.sql ]]; then
    run_check "clickhouse mart ddl" compose exec -T clickhouse clickhouse-client \
      --user "${ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME:-vidyaverse}" \
      --password "${ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD:-vidyaverse-clickhouse-password}" \
      --multiquery < backend/warehouse/clickhouse_schema.sql
  else
    mark_fail "clickhouse schema file missing"
  fi

  run_check "minio artifact bucket" compose run --rm minio-init

  python3 - "${BACKEND_HEALTH_URL:-http://localhost:8000/health}" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
payload = json.loads(urllib.request.urlopen(url, timeout=10).read().decode("utf-8"))
print("[summary] backend_status=", payload.get("status"), sep="")
print("[summary] checks=", json.dumps(payload.get("checks", {}), sort_keys=True), sep="")
print("[summary] operational=", json.dumps(payload.get("operational", {}), sort_keys=True), sep="")
PY

  printf '[summary] passed=%s failed=%s\n' "${checks_passed}" "${checks_failed}"
  if [[ "${checks_failed}" -gt 0 ]]; then
    return 1
  fi
}

main "$@"
