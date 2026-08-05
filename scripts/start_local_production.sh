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
    BACKEND_REUSED=1
    echo "Reusing healthy VidyaVerse backend already listening on ${BACKEND_PORT}."
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
export MONGODB_URL="${MONGODB_URL:-mongodb://${MONGO_INITDB_ROOT_USERNAME}:${MONGO_INITDB_ROOT_PASSWORD}@${LOCAL_DOCKER_MONGO_HOST}:${MONGO_HOST_PORT}/${MONGODB_DB_NAME}?authSource=admin&directConnection=true}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED="${ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED:-true}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST="${ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST:-127.0.0.1}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT="${ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT:-8123}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE="${ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE:-vidyaverse}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME="${ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME:-vidyaverse}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD="${ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD:-vidyaverse-clickhouse-password}"
export ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE="${ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE:-false}"
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

ensure_mongo_keyfile
docker compose up -d mongo redis clickhouse minio minio-init

if ! nc -z 127.0.0.1 "${MONGO_HOST_PORT}" >/dev/null 2>&1; then
  echo "MongoDB is not listening on 127.0.0.1:${MONGO_HOST_PORT}."
  exit 1
fi
if ! nc -z 127.0.0.1 6379 >/dev/null 2>&1; then
  echo "Redis is not listening on 127.0.0.1:6379."
  exit 1
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
