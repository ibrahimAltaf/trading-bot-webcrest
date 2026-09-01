#!/usr/bin/env bash
# Production-style multi-worker API (optional). Same root resolution as run_api.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}"
export PORT="${PORT:-6000}"
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
exec gunicorn src.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w "${WEB_CONCURRENCY}" \
  -b "0.0.0.0:${PORT}" \
  --timeout 120 \
  "$@"
