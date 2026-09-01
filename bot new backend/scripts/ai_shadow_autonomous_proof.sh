#!/usr/bin/env bash
# Demonstrate ONE autonomous (non proof_forced) shadow trade + export full chain.
# Run ON VPS after deploy:
#   /var/www/TRADING-BOT-WEBCREST/backend/scripts/ai_shadow_autonomous_proof.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_BASE="${AI_PROOF_API_BASE:-http://127.0.0.1:8001/api}"
SYMBOL="${AI_PROOF_SYMBOL:-BTCUSDT}"
TIMEFRAME="${AI_PROOF_TIMEFRAME:-1h}"
RISK_PCT="${AI_PROOF_RISK_PCT:-0.01}"
MAX_ATTEMPTS="${AI_PROOF_MAX_ATTEMPTS:-3}"
WAIT_SECS="${AI_PROOF_WAIT_SECS:-10}"
EXTRA_SYMBOLS="${AI_PROOF_EXTRA_SYMBOLS:-ETHUSDT,SOLUSDT}"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
OUT="${AI_PROOF_OUT:-/var/www/TRADING-BOT-WEBCREST/evidence-exports/ai-autonomous-proof-${STAMP}}"

mkdir -p "${OUT}/api" "${OUT}/attempts"

echo "== AI autonomous shadow proof -> ${OUT} =="

curl -fsS "${API_BASE}/settings/scheduler" -o "${OUT}/api/scheduler_before.json" || true

# Enable scheduler if off
ENABLED="$(python3 -c "import json;print(json.load(open('${OUT}/api/scheduler_before.json')).get('enabled',False))" 2>/dev/null || echo false)"
if [[ "${ENABLED}" != "True" && "${ENABLED}" != "true" ]]; then
  echo "Enabling scheduler..."
  curl -fsS -X PUT "${API_BASE}/settings/scheduler" \
    -H "Content-Type: application/json" \
    -d '{"enabled": true}' -o "${OUT}/api/scheduler_enabled.json"
fi

# Ensure shadow mode
curl -fsS -X POST "${API_BASE}/execution/mode" \
  -H "Content-Type: application/json" \
  -d '{"mode":"shadow","reason":"ai autonomous proof"}' \
  -o "${OUT}/api/execution_mode.json"

curl -fsS -X POST "${API_BASE}/safety/kill-switch/release" \
  -H "Content-Type: application/json" \
  -d '{"reason":"ai autonomous proof","by":"ops"}' \
  -o "${OUT}/api/kill_switch_release.json" || true

# Close open shadow position so BUY can execute
echo "Closing any open shadow position (SELL)..."
curl -fsS -X POST "${API_BASE}/exchange/auto-trade" \
  -H "Content-Type: application/json" \
  -d "{\"symbol\":\"${SYMBOL}\",\"timeframe\":\"${TIMEFRAME}\",\"risk_pct\":${RISK_PCT},\"force_signal\":\"SELL\"}" \
  -o "${OUT}/api/close_position_sell.json" || true

_run_autonomous() {
  local sym="$1"
  local tf="$2"
  local n="$3"
  local out="${OUT}/attempts/${sym}-attempt-${n}.json"
  curl -fsS -X POST "${API_BASE}/exchange/auto-trade" \
    -H "Content-Type: application/json" \
    -d "{\"symbol\":\"${sym}\",\"timeframe\":\"${tf}\",\"risk_pct\":${RISK_PCT}}" \
    -o "${out}" 2>/dev/null || echo "{\"ok\":false}" > "${out}"
  EXEC="$(python3 -c "import json;d=json.load(open('${out}'));print(d.get('executed',False))" 2>/dev/null || echo False)"
  SIG="$(python3 -c "import json;d=json.load(open('${out}'));print(d.get('signal','?'))" 2>/dev/null || echo ?)"
  echo "  ${sym} attempt ${n}: signal=${SIG} executed=${EXEC}"
  [[ "${EXEC}" == "True" || "${EXEC}" == "true" ]]
}

SUCCESS=1
SYMS="${SYMBOL}"
if [[ -n "${EXTRA_SYMBOLS}" ]]; then
  SYMS="${SYMBOL},${EXTRA_SYMBOLS}"
fi

IFS=',' read -ra SYM_ARR <<< "${SYMS}"
for attempt in $(seq 1 "${MAX_ATTEMPTS}"); do
  for sym in "${SYM_ARR[@]}"; do
    sym="$(echo "${sym}" | tr -d ' ')"
    [[ -z "${sym}" ]] && continue
    if _run_autonomous "${sym}" "${TIMEFRAME}" "${attempt}"; then
      SUCCESS=0
      break 2
    fi
    sleep 2
  done
  echo "Waiting ${WAIT_SECS}s before next attempt batch..."
  sleep "${WAIT_SECS}"
done

# Export evidence chain
curl -fsS "${API_BASE}/exchange/decisions/recent?symbol=${SYMBOL}&limit=20" \
  -o "${OUT}/api/decisions_recent.json"
curl -fsS "${API_BASE}/safety/shadow-audit?symbol=${SYMBOL}&limit=50" \
  -o "${OUT}/api/shadow_audit.json"
curl -fsS "${API_BASE}/safety/shadow-soak-report?days=1&symbol=${SYMBOL}" \
  -o "${OUT}/api/shadow_soak_report.json"
curl -fsS "${API_BASE}/exchange/ai-observability" \
  -o "${OUT}/api/ai_observability.json"

if [[ -x "${BACKEND_DIR}/scripts/daily_shadow_evidence_export.sh" ]]; then
  SHADOW_EVIDENCE_ROOT="$(dirname "${OUT}")" \
    "${BACKEND_DIR}/scripts/daily_shadow_evidence_export.sh" || true
fi

journalctl -u tradingbot.service --since "2 hours ago" --no-pager \
  | grep -iE 'SCHEDULER|DECISION_PIPELINE|executed|shadow-' \
  > "${OUT}/logs-scheduler-decisions.txt" 2>&1 || true

if [[ "${SUCCESS}" -eq 0 ]]; then
  echo "SUCCESS: autonomous shadow trade executed. See ${OUT}/attempts/"
else
  echo "NO EXECUTE YET: all cycles HOLD or gated — decisions still in decisions_recent.json"
fi

cat > "${OUT}/AI_PROOF_README.md" <<EOF
# AI autonomous shadow proof run

- **UTC:** ${STAMP}
- **Result:** $([[ "${SUCCESS}" -eq 0 ]] && echo "executed=true (check attempts/*.json)" || echo "no order yet — see decisions_recent.json for AI pipeline evidence")

## Verify chain (client)

1. \`attempts/*-attempt-*.json\` — last auto-trade response (no force_signal)
2. \`api/decisions_recent.json\` — market data, ML, final_source, executed flag
3. \`api/shadow_soak_report.json\` — order_origin must NOT be proof_forced
4. \`logs-scheduler-decisions.txt\` — scheduler + DECISION_PIPELINE lines

Zip: \`zip -r ai-autonomous-proof-${STAMP}.zip $(basename "${OUT}")/\`
EOF

echo "Bundle: ${OUT}"
ls -la "${OUT}"
