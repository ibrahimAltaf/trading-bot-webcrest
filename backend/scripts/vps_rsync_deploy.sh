#!/usr/bin/env bash
# Deploy backend from laptop → VPS (preserves remote .env, venv, data/).
#
# Usage (on your Mac):
#   cd "bot new backend"
#   VPS_HOST=root@147.93.96.42 ./scripts/vps_rsync_deploy.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VPS_HOST="${VPS_HOST:-root@147.93.96.42}"
REMOTE_BACKEND="${REMOTE_BACKEND:-/var/www/TRADING-BOT-WEBCREST/backend}"

echo "== rsync ${SRC_DIR} -> ${VPS_HOST}:${REMOTE_BACKEND}/ =="
rsync -avz --delete \
  --exclude '.git' \
  --exclude 'venv' --exclude '.venv' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude '__pycache__' --exclude '*.pyc' \
  "${SRC_DIR}/" "${VPS_HOST}:${REMOTE_BACKEND}/"

echo "== restart + smoke on VPS =="
ssh "${VPS_HOST}" bash -s <<EOF
set -euo pipefail
systemctl restart tradingbot.service
sleep 6
curl -fsS http://127.0.0.1:8001/api/status | head -c 200
echo ""
curl -fsS http://127.0.0.1:8001/api/execution/mode | head -c 200
echo ""
echo "Deploy smoke OK"
EOF

echo "Done. Run post-deploy bundle on VPS:"
echo "  ssh ${VPS_HOST} '${REMOTE_BACKEND}/scripts/post_deploy_verify_and_bundle.sh'"
