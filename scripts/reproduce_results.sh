#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

if [[ ! -d "${BACKEND_DIR}" ]]; then
  echo "backend directory not found at ${BACKEND_DIR}" >&2
  exit 1
fi

if [[ -f "${BACKEND_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${BACKEND_DIR}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 is required" >&2
  exit 1
fi

echo "[reproduce] Running temporal holdout benchmark..."
"${PYTHON_BIN}" "${BACKEND_DIR}/benchmarks/run_offline_benchmarks.py" \
  --profile production_temporal_holdout \
  --out "${BACKEND_DIR}/benchmarks/results.production_temporal_holdout.json"

echo "[reproduce] Running ranking lifecycle pipeline..."
"${PYTHON_BIN}" "${BACKEND_DIR}/scripts/run_model_lifecycle_pipeline.py"

echo "[reproduce] Updating README metadata snapshot..."
"${PYTHON_BIN}" "${BACKEND_DIR}/scripts/publish_model_metadata.py"

echo "[reproduce] Done."
