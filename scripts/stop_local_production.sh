#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT_DIR}/.local-runtime"
BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-3002}"

for session in vidyaverse-backend vidyaverse-frontend; do
  screen -S "${session}" -X quit >/dev/null 2>&1 || true
done

for service in backend frontend; do
  pid_file="${LOG_DIR}/${service}.pid"
  if [[ ! -f "${pid_file}" ]]; then
    continue
  fi
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${pid_file}"
done

stop_listener_if_matches() {
  local port="$1"
  local pattern="$2"
  local pid
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    command_line="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
    if [[ "${command_line}" == *"${pattern}"* ]]; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done < <(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)
}

stop_listener_if_matches "${BACKEND_PORT}" "uvicorn app.main:app"
stop_listener_if_matches "${FRONTEND_PORT}" "next-server"

echo "Stopped VidyaVerse local production processes."
