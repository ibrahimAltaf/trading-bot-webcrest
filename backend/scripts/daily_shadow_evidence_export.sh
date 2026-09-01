#!/usr/bin/env bash
# Daily shadow evidence export — run from cron on the VPS.
# Writes JSON to disk OUTSIDE the database (filesystem backups / rsync / download).
#
# Example cron (02:00 UTC daily during 48–72h test):
#   0 2 * * * /var/www/TRADING-BOT-WEBCREST/backend/scripts/daily_shadow_evidence_export.sh >> /var/log/shadow-evidence-export.log 2>&1
#
# Manual:
#   bash scripts/daily_shadow_evidence_export.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EVIDENCE_ROOT="${SHADOW_EVIDENCE_ROOT:-/var/www/TRADING-BOT-WEBCREST/evidence-exports}"
API_BASE="${SHADOW_API_BASE:-http://127.0.0.1:8001/api}"
SYMBOL="${SHADOW_EVIDENCE_SYMBOL:-BTCUSDT}"
WINDOW_DAYS="${SHADOW_EVIDENCE_DAYS:-3}"
DATE_UTC="$(date -u +%Y-%m-%d)"
TIME_UTC="$(date -u +%H%M%S)"
OUT_DIR="${EVIDENCE_ROOT}/${DATE_UTC}"

mkdir -p "${OUT_DIR}"

echo "[$(date -u -Iseconds)] shadow evidence export start -> ${OUT_DIR}"

# --- API snapshots (lightweight; survives even if DB export script fails) ---
curl -fsS "${API_BASE}/safety/shadow-soak-report?days=${WINDOW_DAYS}&symbol=${SYMBOL}" \
  -o "${OUT_DIR}/shadow-soak-report-api.json"
curl -fsS "${API_BASE}/safety/shadow-audit?symbol=${SYMBOL}&limit=200" \
  -o "${OUT_DIR}/shadow-audit-api.json"
curl -fsS "${API_BASE}/exchange/orders/all?mode=shadow&symbol=${SYMBOL}&limit=200" \
  -o "${OUT_DIR}/shadow-orders-all-api.json"
curl -fsS "${API_BASE}/execution/mode" -o "${OUT_DIR}/execution-mode-api.json"

# --- DB-backed export (canonical order_origin / PnL slices) ---
cd "${BACKEND_DIR}"
if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${BACKEND_DIR}/.env"
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "WARN: DATABASE_URL not set — API snapshots only" >&2
else
  if [[ -d "${BACKEND_DIR}/venv/bin" ]]; then
    # shellcheck disable=SC1091
    source "${BACKEND_DIR}/venv/bin/activate"
  fi
  export PYTHONPATH="${BACKEND_DIR}"
  python "${BACKEND_DIR}/scripts/export_shadow_soak_evidence.py" \
    --days "${WINDOW_DAYS}" \
    --symbol "${SYMBOL}" \
    --out "${OUT_DIR}/db-export" \
    --dated
fi

# --- Run metadata ---
cat > "${OUT_DIR}/run_meta.json" <<EOF
{
  "exported_at_utc": "$(date -u -Iseconds)",
  "hostname": "$(hostname)",
  "api_base": "${API_BASE}",
  "symbol": "${SYMBOL}",
  "window_days": ${WINDOW_DAYS},
  "evidence_root": "${EVIDENCE_ROOT}"
}
EOF

# Optional: second copy with timestamp for intra-day manual runs
if [[ "${SHADOW_EVIDENCE_TIMESTAMPED:-0}" == "1" ]]; then
  cp -a "${OUT_DIR}" "${EVIDENCE_ROOT}/${DATE_UTC}-${TIME_UTC}"
fi

echo "[$(date -u -Iseconds)] shadow evidence export done -> ${OUT_DIR}"
ls -la "${OUT_DIR}"
