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
  /usr/bin/curl -fsS "${url}/health" 2>/dev/null | python3 -c 'import json, sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("service") == "VidyaVerse API" else 1)' >/dev/null 2>&1
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
  if /usr/bin/curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    FRONTEND_REUSED=1
    echo "Reusing healthy frontend already listening on ${FRONTEND_PORT}."
  else
    echo "Frontend port ${FRONTEND_PORT} is already in use, but / is not reachable. Stop it first or set FRONTEND_PORT."
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

  for _ in $(seq 1 90); do
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

if [[ ! -f "${FRONTEND_DIR}/.next/standalone/frontend/server.js" ]]; then
  echo "Frontend production bundle missing; running npm build first."
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
    if /usr/bin/curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
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
