#!/usr/bin/env bash
# Run API from any cwd (VPS systemd, cron, manual). Resolves backend root automatically.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}"
export PORT="${PORT:-6000}"
exec uvicorn src.main:app --host "${HOST:-0.0.0.0}" --port "${PORT}" "$@"
