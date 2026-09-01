#!/usr/bin/env bash
# Full deploy ON THE VPS (git reset → rsync → restart → autonomous proof).
# Run as root on srv759398:
#   cd /var/www/TRADING-BOT-WEBCREST && git pull origin main
#   bash "bot new backend/scripts/vps_on_server_deploy.sh"
#
set -euo pipefail

REPO="${VPS_REPO_ROOT:-/var/www/TRADING-BOT-WEBCREST}"
SRC="${REPO}/bot new backend"
BACKEND="${VPS_BACKEND_DIR:-${REPO}/backend}"
API_PORT="${VPS_API_PORT:-8001}"

echo "== VPS on-server deploy =="
cd "${REPO}"

echo "== git sync (hard reset — restores full bot new backend/) =="
git fetch origin main
git checkout main
git reset --hard origin/main
echo "HEAD: $(git rev-parse --short HEAD) $(git log -1 --format='%s')"

echo "== preflight source tree =="
for f in requirements.txt src/main.py src/live/auto_trade_engine.py; do
  if [[ ! -f "${SRC}/${f}" ]]; then
    echo "FATAL: missing ${SRC}/${f} — aborting before rsync (prevents partial wipe)" >&2
    exit 1
  fi
done
echo "  source OK ($(find "${SRC}" -type f | wc -l) files)"

echo "== rsync bot new backend -> backend =="
rsync -av --delete \
  --exclude 'venv/' --exclude '.venv/' \
  --exclude 'data/' --exclude '.env' \
  --exclude '__pycache__/' --exclude '*.pyc' \
  "${SRC}/" "${BACKEND}/"

chmod +x "${BACKEND}/scripts/"*.sh 2>/dev/null || true

# Ensure confidence gate matches code default (VPS .env often still has 0.55).
ENV_FILE="${BACKEND}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  if grep -q '^ML_MIN_TRADE_CONFIDENCE=' "${ENV_FILE}"; then
    sed -i 's/^ML_MIN_TRADE_CONFIDENCE=.*/ML_MIN_TRADE_CONFIDENCE=0.50/' "${ENV_FILE}"
  else
    echo 'ML_MIN_TRADE_CONFIDENCE=0.50' >> "${ENV_FILE}"
  fi
  echo "  .env ML_MIN_TRADE_CONFIDENCE=$(grep '^ML_MIN_TRADE_CONFIDENCE=' "${ENV_FILE}" | cut -d= -f2)"

  # Phase 2A adaptive-thresholds validation (Saad concern #3): turn on the
  # per-cycle adaptive engine so entry-confidence floors / RSI bands / SL-TP
  # actually recompute with market regime instead of staying fixed.
  if grep -q '^FULLY_ADAPTIVE_ENGINE=' "${ENV_FILE}"; then
    sed -i 's/^FULLY_ADAPTIVE_ENGINE=.*/FULLY_ADAPTIVE_ENGINE=true/' "${ENV_FILE}"
  else
    echo 'FULLY_ADAPTIVE_ENGINE=true' >> "${ENV_FILE}"
  fi
  echo "  .env FULLY_ADAPTIVE_ENGINE=$(grep '^FULLY_ADAPTIVE_ENGINE=' "${ENV_FILE}" | cut -d= -f2)"
fi

if [[ -x "${BACKEND}/venv/bin/pip" ]]; then
  echo "== pip install (quick) =="
  "${BACKEND}/venv/bin/pip" install -q -r "${BACKEND}/requirements.txt"
  "${BACKEND}/venv/bin/pip" install -q -r "${BACKEND}/requirements-ml.txt" 2>/dev/null || true
fi

echo "== restart tradingbot =="
systemctl restart tradingbot.service
sleep 8

echo "== smoke =="
curl -fsS "http://127.0.0.1:${API_PORT}/api/status" | head -c 300
echo ""
curl -fsS "http://127.0.0.1:${API_PORT}/api/execution/mode" | head -c 200
echo ""

echo "== release kill switch + shadow mode =="
curl -fsS -X POST "http://127.0.0.1:${API_PORT}/api/safety/kill-switch/release" \
  -H "Content-Type: application/json" \
  -d '{"reason":"post-deploy","by":"ops"}' >/dev/null || true
curl -fsS -X POST "http://127.0.0.1:${API_PORT}/api/execution/mode" \
  -H "Content-Type: application/json" \
  -d '{"mode":"shadow","reason":"post-deploy"}' >/dev/null || true
curl -fsS -X PUT "http://127.0.0.1:${API_PORT}/api/settings/scheduler" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' >/dev/null || true

echo "== autonomous proof (quick — 3 batches, 5m+1h) =="
AI_PROOF_API_BASE="http://127.0.0.1:${API_PORT}/api" \
AI_PROOF_MAX_ATTEMPTS=3 \
AI_PROOF_TIMEFRAME=5m \
  "${BACKEND}/scripts/ai_shadow_autonomous_proof.sh" || true
# Also try 1h once if 5m proof did not execute
AI_PROOF_API_BASE="http://127.0.0.1:${API_PORT}/api" \
AI_PROOF_MAX_ATTEMPTS=1 \
AI_PROOF_TIMEFRAME=1h \
  "${BACKEND}/scripts/ai_shadow_autonomous_proof.sh" || true

echo "== shadow soak origin =="
curl -fsS "http://127.0.0.1:${API_PORT}/api/safety/shadow-soak-report?days=7" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('shadow_orders_origin_summary'), indent=2))"

echo "== DONE =="
