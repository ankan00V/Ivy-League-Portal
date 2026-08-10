#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
LOG_DIR="${ROOT_DIR}/.local-runtime"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3002}"

mkdir -p "${LOG_DIR}"

ensure_mongo_keyfile() {
  local keyfile="${LOG_DIR}/mongo-keyfile"
  if [[ ! -f "${keyfile}" ]]; then
    openssl rand -base64 756 > "${keyfile}"
  fi
  chmod 400 "${keyfile}"
}

is_vidyaverse_backend() {
  local url="$1"
  # Probes /health/ready, not /health. /health is now a static liveness reply
  # that returns as soon as uvicorn binds, so waiting on it would let the
  # harness proceed to the smoke test while Mongo, Redis and the model artifacts
  # were still loading. Readiness is what "the backend is up" has to mean here.
  /usr/bin/curl -fsS "${url}/health/ready" 2>/dev/null | python3 -c 'import json, sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("service") == "VidyaVerse API" and payload.get("status") == "healthy" else 1)' >/dev/null 2>&1
}

is_vidyaverse_frontend() {
  local url="${1%/}"
  local homepage stylesheet
  homepage="$(/usr/bin/curl -fsS "${url}/" 2>/dev/null)" || return 1
  stylesheet="$(printf '%s' "${homepage}" | sed -nE 's/.*href="([^"?]*\.css)(\?[^" ]*)?".*/\1/p' | head -n 1)"
  [[ -n "${stylesheet}" ]] || return 1
  /usr/bin/curl -fsS -o /dev/null "${url}${stylesheet}" 2>/dev/null
}

# is_vidyaverse_frontend answers "is something alive on this port", which is not
# the same question as "is it running the code that is currently on disk". Every
# frontend fix in this repo compiles into .next, but scripts/start-standalone.mjs
# copies .next/static into the standalone tree once, at boot, and the server
# resolves its asset root at the same moment. A server left running across a
# rebuild therefore keeps serving the previous build and returns 404 for every
# asset the new one emitted - which presents as "the fix did nothing" rather than
# as "the server is stale", and has cost several rounds of debugging the wrong
# layer. The two checks below make the reuse decision depend on freshness.

backend_source_is_newer() {
  # Any Python file edited since the process started means it is running code
  # that no longer exists on disk.
  local pid started
  pid="$(lsof -nP -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -t 2>/dev/null | head -n 1)" || return 1
  [[ -n "${pid}" ]] || return 1
  started="$(ps -o lstart= -p "${pid}" 2>/dev/null)" || return 1
  [[ -n "${started}" ]] || return 1
  local marker="${LOG_DIR}/.backend-start-marker"
  touch -d "${started}" "${marker}" 2>/dev/null || date -j -f "%a %b %e %T %Y" "${started}" "+%Y%m%d%H%M.%S" 2>/dev/null \
    | xargs -I{} touch -t {} "${marker}" 2>/dev/null || return 1
  local newer
  newer="$(find "${BACKEND_DIR}/app" -name '*.py' -newer "${marker}" -print -quit 2>/dev/null || true)"
  [[ -n "${newer}" ]]
}

backend_serves_current_code() {
  local url="${1%/}" reported
  # is_vidyaverse_backend only proves something is answering. The backend reads
  # its settings once at import, so a process left running across an edit keeps
  # serving the old values: the feed ceiling was raised to 2000 in config while
  # an eighteen-hour-old process went on returning 600 rows, which looked like
  # the change had not worked. Comparing a live setting against the file on disk
  # is the cheapest way to notice.
  local on_disk
  on_disk="$(cd "${BACKEND_DIR}" && ./venv/bin/python -c \
    'from app.core.config import settings; print(settings.OPPORTUNITY_FEED_MAX_LIMIT)' 2>/dev/null)" || return 0
  [[ -n "${on_disk}" ]] || return 0
  reported="$(/usr/bin/curl -fsS "${url}/health/ready" 2>/dev/null \
    | python3 -c 'import json,sys; print((json.load(sys.stdin).get("config") or {}).get("feed_max_limit",""))' 2>/dev/null)"
  # Older builds do not report it; absence is not evidence of staleness.
  [[ -z "${reported}" ]] && return 0
  [[ "${reported}" == "${on_disk}" ]]
}

stop_backend() {
  screen -S vidyaverse-backend -X quit >/dev/null 2>&1 || true
  local pids attempt
  pids="$(lsof -nP -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  [[ -n "${pids}" ]] || return 0
  kill ${pids} >/dev/null 2>&1 || true
  for attempt in $(seq 1 10); do
    lsof -nP -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1 || return 0
    sleep 1
  done
  lsof -nP -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN -t 2>/dev/null | xargs kill -9 >/dev/null 2>&1 || true
  sleep 1
}

frontend_build_is_stale() {
  local stamp="${FRONTEND_DIR}/.next/BUILD_ID"
  # No build at all counts as stale so the build step below runs.
  [[ -f "${stamp}" ]] || return 0
  local targets=() candidate newer
  for candidate in src public next.config.ts next.config.mjs next.config.js package.json tsconfig.json; do
    [[ -e "${FRONTEND_DIR}/${candidate}" ]] && targets+=("${FRONTEND_DIR}/${candidate}")
  done
  [[ ${#targets[@]} -gt 0 ]] || return 1
  newer="$(find "${targets[@]}" -type f -newer "${stamp}" -print -quit 2>/dev/null || true)"
  [[ -n "${newer}" ]]
}

frontend_serves_current_build() {
  local url="${1%/}" build_id
  build_id="$(cat "${FRONTEND_DIR}/.next/BUILD_ID" 2>/dev/null || true)"
  [[ -n "${build_id}" ]] || return 1
  # This path embeds the build id, so it is the cheapest way to tell a server
  # running the current build apart from one running any older build.
  /usr/bin/curl -fsS -o /dev/null "${url}/_next/static/${build_id}/_buildManifest.js" 2>/dev/null
}

stop_frontend() {
  screen -S vidyaverse-frontend -X quit >/dev/null 2>&1 || true
  local pids attempt
  pids="$(lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN -t 2>/dev/null || true)"
  [[ -n "${pids}" ]] || return 0
  kill ${pids} >/dev/null 2>&1 || true
  for attempt in $(seq 1 10); do
    lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1 || return 0
    sleep 1
  done
  lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN -t 2>/dev/null | xargs kill -9 >/dev/null 2>&1 || true
  sleep 1
}

BACKEND_REUSED=0
if lsof -nP -iTCP:"${BACKEND_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  if is_vidyaverse_backend "http://127.0.0.1:${BACKEND_PORT}"; then
    if backend_source_is_newer || ! backend_serves_current_code "http://127.0.0.1:${BACKEND_PORT}"; then
      echo "Backend on ${BACKEND_PORT} is running older code; restarting it."
      stop_backend
    else
      BACKEND_REUSED=1
      echo "Reusing healthy VidyaVerse backend already listening on ${BACKEND_PORT}."
    fi
  else
    echo "Backend port ${BACKEND_PORT} is already in use, but it is not VidyaVerse. Stop it first or set BACKEND_PORT."
    exit 1
  fi
fi

FRONTEND_REUSED=0
if lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  if is_vidyaverse_frontend "http://127.0.0.1:${FRONTEND_PORT}"; then
    if frontend_build_is_stale; then
      echo "Frontend sources changed since the last build; rebuilding and restarting it."
      stop_frontend
    elif ! frontend_serves_current_build "http://127.0.0.1:${FRONTEND_PORT}"; then
      echo "Frontend on ${FRONTEND_PORT} is serving an older build; restarting it."
      stop_frontend
    else
      FRONTEND_REUSED=1
      echo "Reusing healthy frontend already serving the current build on ${FRONTEND_PORT}."
    fi
  else
    echo "Frontend port ${FRONTEND_PORT} is already in use, but its compiled assets are not healthy. Stop it first or set FRONTEND_PORT."
    exit 1
  fi
fi

export MONGO_INITDB_ROOT_USERNAME="${MONGO_INITDB_ROOT_USERNAME:-vidyaverse}"
export MONGO_INITDB_ROOT_PASSWORD="${MONGO_INITDB_ROOT_PASSWORD:-replace-with-mongo-root-password}"
export MONGODB_DB_NAME="${MONGODB_DB_NAME:-vidyaverse}"
export MONGO_HOST_PORT="${MONGO_HOST_PORT:-27018}"
export LOCAL_DOCKER_MONGO_HOST="${LOCAL_DOCKER_MONGO_HOST:-127.0.0.1}"
# backend/.env is the source of truth for which database this app talks to, and
# MongoDB Atlas is the real one. Exporting a local-Docker URL here silently beat
# it: pydantic ranks environment variables above the .env file, so the app read
# a local copy while every script run without these exports read Atlas. The two
# drifted - the local copy accumulated rows Atlas never saw and carried domain
# values Atlas did not - and the app was serving the wrong database entirely.
# The Docker instance is still started below as a fallback for a machine with no
# configured Atlas URL.
ENV_MONGODB_URL="$(sed -n 's/^MONGODB_URL=//p' "${BACKEND_DIR}/.env" 2>/dev/null | head -n 1)"
if [[ -n "${ENV_MONGODB_URL}" ]]; then
  export MONGODB_URL="${MONGODB_URL:-${ENV_MONGODB_URL}}"
else
  export MONGODB_URL="${MONGODB_URL:-mongodb://${MONGO_INITDB_ROOT_USERNAME}:${MONGO_INITDB_ROOT_PASSWORD}@${LOCAL_DOCKER_MONGO_HOST}:${MONGO_HOST_PORT}/${MONGODB_DB_NAME}?authSource=admin&directConnection=true}"
fi
# Same rule as MONGODB_URL above: backend/.env decides which services this app
# talks to, and an exported default here would silently beat it. Redis is on
# Upstash, so forcing a local container both ignores the real cache and makes
# Docker a hard dependency for a stack that no longer needs it.
ENV_REDIS_URL="$(sed -n 's/^REDIS_URL=//p' "${BACKEND_DIR}/.env" 2>/dev/null | head -n 1)"
if [[ -n "${ENV_REDIS_URL}" ]]; then
  export REDIS_URL="${REDIS_URL:-${ENV_REDIS_URL}}"
else
  export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
fi
# Third instance of the same override bug, after MONGODB_URL and REDIS_URL:
# these defaults pointed the warehouse at a local container while .env pointed
# it at ClickHouse Cloud. With no local container running, every readiness probe
# retried a refused connection to 127.0.0.1:8123 and took 43-56 seconds - the
# app was up and healthy the whole time, it just could not answer quickly enough
# to look it. env_or_default reads .env first so the configured host wins.
env_or_default() {
  local key="$1" fallback="$2" from_env
  from_env="$(sed -n "s/^${key}=//p" "${BACKEND_DIR}/.env" 2>/dev/null | head -n 1)"
  printf '%s' "${from_env:-$fallback}"
}
export ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED="${ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED true)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST="${ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST 127.0.0.1)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT="${ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT 8123)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE="${ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE vidyaverse)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME="${ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME vidyaverse)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD="${ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD vidyaverse-clickhouse-password)}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE="${ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE:-$(env_or_default ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE false)}"
export MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL="${MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL:-http://127.0.0.1:9002}"
export MLOPS_MODEL_ARTIFACT_S3_REGION="${MLOPS_MODEL_ARTIFACT_S3_REGION:-us-east-1}"
export MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID="${MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID:-minioadmin}"
export MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY="${MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY:-minioadmin}"
export MODEL_ARTIFACT_BUCKET="${MODEL_ARTIFACT_BUCKET:-vidyaverse-model-artifacts}"
# Local fallback for the learned ranker. ensure_learned_ranker_artifact_ready
# tries LEARNED_RANKER_ARTIFACT_URI first and falls back to this path, so the
# harness still boots with a working ranker when the object store has not been
# seeded. The checksum is verified either way.
export LEARNED_RANKER_MODEL_PATH="${LEARNED_RANKER_MODEL_PATH:-${BACKEND_DIR}/models/learned_ranker.lgb.txt}"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"
export BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://127.0.0.1:${BACKEND_PORT}}"

# Mongo, Redis and ClickHouse are all hosted now (Atlas, Upstash, ClickHouse
# Cloud). Starting local containers for them is not just redundant - it made
# Docker a hard requirement to boot the app, so a stopped daemon failed a stack
# that had no local dependency left. Containers are started only for the
# services still pointed at localhost.
# Split by whether the app can boot without them.
NEEDS_LOCAL_SERVICES=()
[[ "${MONGODB_URL}" == *"127.0.0.1"* || "${MONGODB_URL}" == *"localhost"* ]] && NEEDS_LOCAL_SERVICES+=(mongo)
[[ "${REDIS_URL}" == *"127.0.0.1"* || "${REDIS_URL}" == *"localhost"* ]] && NEEDS_LOCAL_SERVICES+=(redis)

# MinIO only backs model artifacts, and ensure_learned_ranker_artifact_ready
# already falls back to LEARNED_RANKER_MODEL_PATH on disk. Treating it as
# required meant a stopped Docker daemon blocked the entire app over an
# optional object store.
OPTIONAL_LOCAL_SERVICES=()
[[ "${MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL}" == *"127.0.0.1"* ]] && OPTIONAL_LOCAL_SERVICES+=(minio minio-init)
if [[ ${#OPTIONAL_LOCAL_SERVICES[@]} -gt 0 ]]; then
  if docker compose up -d "${OPTIONAL_LOCAL_SERVICES[@]}" >/dev/null 2>&1; then
    echo "Optional local services started: ${OPTIONAL_LOCAL_SERVICES[*]}."
  else
    echo "Optional local services unavailable (${OPTIONAL_LOCAL_SERVICES[*]}); the learned ranker will use its on-disk artifact."
  fi
fi

if [[ ${#NEEDS_LOCAL_SERVICES[@]} -gt 0 ]]; then
  ensure_mongo_keyfile
  if ! docker compose up -d "${NEEDS_LOCAL_SERVICES[@]}"; then
    echo "Could not start local services (${NEEDS_LOCAL_SERVICES[*]}). Is Docker running?"
    exit 1
  fi
  if [[ " ${NEEDS_LOCAL_SERVICES[*]} " == *" mongo "* ]] && ! nc -z 127.0.0.1 "${MONGO_HOST_PORT}" >/dev/null 2>&1; then
    echo "MongoDB is not listening on 127.0.0.1:${MONGO_HOST_PORT}."
    exit 1
  fi
  if [[ " ${NEEDS_LOCAL_SERVICES[*]} " == *" redis "* ]] && ! nc -z 127.0.0.1 6379 >/dev/null 2>&1; then
    echo "Redis is not listening on 127.0.0.1:6379."
    exit 1
  fi
else
  echo "All datastores are hosted (Atlas / Upstash / ClickHouse Cloud); skipping local containers."
fi

export LLM_PROVIDER="${LLM_PROVIDER:-openai_compatible}"
export LLM_MODEL="${LLM_MODEL:-meta/llama-3.1-8b-instruct}"
export RAG_LLM_MODEL="${RAG_LLM_MODEL:-${LLM_MODEL}}"

if [[ "${BACKEND_REUSED}" -eq 0 ]]; then
  (
    cd "${BACKEND_DIR}"
    "${BACKEND_DIR}/venv/bin/python" scripts/validate_env.py
  )
  if command -v screen >/dev/null 2>&1; then
    screen -S vidyaverse-backend -X quit >/dev/null 2>&1 || true
    screen -dmS vidyaverse-backend bash -lc \
      "cd \"${BACKEND_DIR}\" && exec \"${BACKEND_DIR}/venv/bin/python\" -m uvicorn app.main:app --host 127.0.0.1 --port \"${BACKEND_PORT}\" >> \"${LOG_DIR}/backend.log\" 2>&1"
    BACKEND_PID=""
    rm -f "${LOG_DIR}/backend.pid"
  else
    (
      cd "${BACKEND_DIR}"
      exec nohup "${BACKEND_DIR}/venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}"
    ) >"${LOG_DIR}/backend.log" 2>&1 &
    BACKEND_PID="$!"
    echo "${BACKEND_PID}" > "${LOG_DIR}/backend.pid"
  fi

  # ~5 minutes. The probe now waits for /health/ready rather than /health, and
  # readiness genuinely exercises Mongo, Redis, ClickHouse, the artifact store
  # and the learned-ranker load, so first boot on a cold cache legitimately
  # exceeds the previous 3-minute budget. Timing out early meant the smoke test
  # ran against a half-started backend and reported failures that were not real.
  for _ in $(seq 1 150); do
    if is_vidyaverse_backend "http://127.0.0.1:${BACKEND_PORT}"; then
      break
    fi
    if [[ -n "${BACKEND_PID}" ]] && ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
      echo "Backend exited during startup. Log:"
      tail -120 "${LOG_DIR}/backend.log"
      exit 1
    fi
    sleep 2
  done
else
  rm -f "${LOG_DIR}/backend.pid"
fi

if [[ ! -f "${FRONTEND_DIR}/.next/standalone/frontend/server.js" ]] || frontend_build_is_stale; then
  echo "Frontend production bundle missing or out of date; running npm build first."
  (
    cd "${FRONTEND_DIR}"
    npm run build
  )
fi

if [[ "${FRONTEND_REUSED}" -eq 0 ]]; then
  if command -v screen >/dev/null 2>&1; then
    screen -S vidyaverse-frontend -X quit >/dev/null 2>&1 || true
    screen -dmS vidyaverse-frontend bash -lc \
      "cd \"${FRONTEND_DIR}\" && exec env NEXT_PUBLIC_API_BASE_URL=\"http://127.0.0.1:${BACKEND_PORT}\" PORT=\"${FRONTEND_PORT}\" npm run start >> \"${LOG_DIR}/frontend.log\" 2>&1"
    FRONTEND_PID=""
    rm -f "${LOG_DIR}/frontend.pid"
  else
    (
      cd "${FRONTEND_DIR}"
      exec env NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}" PORT="${FRONTEND_PORT}" nohup npm run start
    ) >"${LOG_DIR}/frontend.log" 2>&1 &
    FRONTEND_PID="$!"
    echo "${FRONTEND_PID}" > "${LOG_DIR}/frontend.pid"
  fi

  for _ in $(seq 1 60); do
    if is_vidyaverse_frontend "http://127.0.0.1:${FRONTEND_PORT}"; then
      break
    fi
    if [[ -n "${FRONTEND_PID}" ]] && ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
      echo "Frontend exited during startup. Log:"
      tail -120 "${LOG_DIR}/frontend.log"
      exit 1
    fi
    sleep 2
  done
else
  rm -f "${LOG_DIR}/frontend.pid"
fi

python3 "${ROOT_DIR}/scripts/smoke_test_local.py" \
  --backend-url "http://127.0.0.1:${BACKEND_PORT}" \
  --frontend-url "http://127.0.0.1:${FRONTEND_PORT}"

echo "Local production-like stack is ready."
echo "Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "Logs:     ${LOG_DIR}"
