#!/usr/bin/env bash
# Post-deploy verification + log bundle for client sign-off.
# Run ON THE VPS after deploy:
#   /var/www/TRADING-BOT-WEBCREST/backend/scripts/post_deploy_verify_and_bundle.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_BASE="${VERIFY_API_BASE:-http://127.0.0.1:8001/api}"
SYMBOL="${VERIFY_SYMBOL:-BTCUSDT}"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
BUNDLE_ROOT="${VERIFY_BUNDLE_ROOT:-/var/www/TRADING-BOT-WEBCREST/evidence-exports}"
OUT="${BUNDLE_ROOT}/post-deploy-verify-${STAMP}"

mkdir -p "${OUT}/api" "${OUT}/logs" "${OUT}/system"

echo "== Post-deploy verify -> ${OUT} =="

_fetch() {
  local name="$1"
  local url="$2"
  if curl -fsS "${url}" -o "${OUT}/api/${name}.json"; then
    echo "  OK ${name}"
  else
    echo "  FAIL ${name}" >&2
    echo "{\"ok\":false,\"error\":\"fetch failed\",\"url\":\"${url}\"}" > "${OUT}/api/${name}.json"
  fi
}

_fetch status "${API_BASE}/status"
_fetch health_db "${API_BASE}/health/db"
_fetch execution_mode "${API_BASE}/execution/mode"
_fetch live_readiness "${API_BASE}/safety/live-readiness"
_fetch shadow_audit "${API_BASE}/safety/shadow-audit?symbol=${SYMBOL}&limit=200"
_fetch shadow_soak_report "${API_BASE}/safety/shadow-soak-report?days=3&symbol=${SYMBOL}"
_fetch shadow_orders "${API_BASE}/exchange/orders/all?mode=shadow&symbol=${SYMBOL}&limit=50"
_fetch exchange_reconcile_shadow "${API_BASE}/safety/exchange-reconcile?mode=shadow&symbol=${SYMBOL}"
_fetch decisions_recent "${API_BASE}/exchange/decisions/recent?symbol=${SYMBOL}&limit=30"
_fetch ai_observability "${API_BASE}/exchange/ai-observability"
_fetch operational_readiness "${API_BASE}/safety/operational-readiness"

# Daily evidence export (if script present)
if [[ -x "${BACKEND_DIR}/scripts/daily_shadow_evidence_export.sh" ]]; then
  SHADOW_EVIDENCE_ROOT="${BUNDLE_ROOT}" "${BACKEND_DIR}/scripts/daily_shadow_evidence_export.sh" \
    || echo "WARN: daily export failed" >&2
fi

# Logs
journalctl -u tradingbot.service -n 500 --no-pager > "${OUT}/logs/journalctl-tradingbot-500.txt" 2>&1 || true
journalctl -u tradingbot.service --since "24 hours ago" --no-pager \
  | grep -iE 'shadow|scheduler|executed|ERROR|STARTUP|restored' \
  > "${OUT}/logs/journalctl-filtered-24h.txt" 2>&1 || true
[[ -f /var/log/shadow-evidence-export.log ]] && \
  cp /var/log/shadow-evidence-export.log "${OUT}/logs/" || true

# System
systemctl status tradingbot.service --no-pager > "${OUT}/system/systemctl-status.txt" 2>&1 || true
df -h / > "${OUT}/system/disk.txt" 2>&1 || true
free -h > "${OUT}/system/memory.txt" 2>&1 || true
uname -a > "${OUT}/system/uname.txt" 2>&1 || true

# Summary markdown
SHADOW_MODE="$(python3 -c "import json;print(json.load(open('${OUT}/api/execution_mode.json')).get('effective_mode','?'))" 2>/dev/null || echo '?')"
LIVE_READY="$(python3 -c "import json;print(json.load(open('${OUT}/api/live_readiness.json')).get('ready_for_live_capital','?'))" 2>/dev/null || echo '?')"
RECON_OK="$(python3 -c "import json;print(json.load(open('${OUT}/api/exchange_reconcile_shadow.json')).get('ok','?'))" 2>/dev/null || echo '?')"
ORDER_COUNT="$(python3 -c "import json;d=json.load(open('${OUT}/api/shadow_audit.json'));print(d.get('unique_shadow_order_ids_count',0))" 2>/dev/null || echo '?')"

cat > "${OUT}/VERIFY_SUMMARY.md" <<EOF
# Post-deploy verification summary

- **Generated (UTC):** ${STAMP}
- **API base:** ${API_BASE}
- **Symbol:** ${SYMBOL}

## Pass/fail snapshot

| Check | Value |
|-------|-------|
| execution_mode | ${SHADOW_MODE} |
| ready_for_live_capital | ${LIVE_READY} |
| shadow order IDs (audit) | ${ORDER_COUNT} |
| exchange-reconcile shadow ok | ${RECON_OK} |

## Bundle contents

- \`api/*.json\` — live API responses at verify time
- \`logs/\` — journalctl (500 lines + 24h filtered)
- \`system/\` — service status, disk, memory

## Client

Send this folder (or zip) with:
\`docs/CLIENT-PHASE2A-SIGNOFF-AND-PHASE2B-KICKOFF.md\` from GitHub.

Zip:
\`cd ${BUNDLE_ROOT} && zip -r post-deploy-verify-${STAMP}.zip post-deploy-verify-${STAMP}/\`
EOF

python3 -c "
import json, pathlib
p = pathlib.Path('${OUT}')
manifest = {
  'generated_at_utc': '${STAMP}',
  'bundle_dir': '${OUT}',
  'api_base': '${API_BASE}',
  'checks': {
    'execution_mode': '${SHADOW_MODE}',
    'ready_for_live_capital': '${LIVE_READY}',
    'shadow_order_ids': '${ORDER_COUNT}',
    'exchange_reconcile_shadow_ok': '${RECON_OK}',
  },
}
(p / 'verify_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
"

echo ""
echo "== Verification bundle ready =="
echo "${OUT}"
echo "Zip: cd ${BUNDLE_ROOT} && zip -r post-deploy-verify-${STAMP}.zip $(basename "${OUT}")/"
ls -la "${OUT}"
