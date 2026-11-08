#!/usr/bin/env bash
#
# Runs both halves of VidyaVerse in one container for Antideploy.
#
# Next.js binds the public port; FastAPI binds loopback only. The public port is
# what the platform probes, so the API gets a bounded head start and Next starts
# regardless of whether it won: a container that never binds its port is the
# single most common deploy failure, and the API's own crash reason is far more
# useful in the logs than a silent port timeout.
set -uo pipefail

: "${PORT:=3000}"
: "${BACKEND_INTERNAL_URL:=http://127.0.0.1:8000}"
export PORT BACKEND_INTERNAL_URL
export HOSTNAME="0.0.0.0"

echo "entrypoint: starting FastAPI on 127.0.0.1:8000"
cd /app/api || exit 1
uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --log-level info &
API_PID=$!

ready=0
for _ in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "entrypoint: FastAPI exited before becoming ready" >&2
    break
  fi
  sleep 2
done

if [ "$ready" = "1" ]; then
  echo "entrypoint: FastAPI ready"
else
  echo "entrypoint: FastAPI not ready; starting Next.js anyway so the public port binds" >&2
fi

echo "entrypoint: starting Next.js on 0.0.0.0:${PORT}"
cd /app/web || exit 1
node server.js &
WEB_PID=$!

shutdown() {
  kill -TERM "$WEB_PID" "$API_PID" 2>/dev/null || true
}
trap shutdown TERM INT

# Exit when either process dies so the platform notices and restarts the
# container instead of serving a half-working app.
while kill -0 "$WEB_PID" 2>/dev/null && kill -0 "$API_PID" 2>/dev/null; do
  sleep 2
done

echo "entrypoint: a supervised process exited; shutting down" >&2
shutdown
wait -n "$WEB_PID" "$API_PID" 2>/dev/null || true
exit 1
