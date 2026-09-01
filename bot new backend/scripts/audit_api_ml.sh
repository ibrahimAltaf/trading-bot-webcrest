#!/usr/bin/env bash
# One-shot API + ML audit (local backend + optional nginx-style /api via Host header).
# Usage:
#   bash scripts/audit_api_ml.sh
#   BACKEND=http://127.0.0.1:8000 PUBLIC_HOST=147.93.96.42 bash scripts/audit_api_ml.sh

set -euo pipefail

BACKEND="${BACKEND:-http://127.0.0.1:8000}"
PUBLIC_HOST="${PUBLIC_HOST:-}"

die() { echo "ERROR: $*" >&2; exit 1; }

have_jq() { command -v jq >/dev/null 2>&1; }

get_json() {
  local url=$1
  local label=$2
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ $label"
  echo "   GET $url"
  local code body
  body=$(curl -sS -w "\n%{http_code}" "$url") || die "curl failed: $url"
  code=$(echo "$body" | tail -n1)
  body=$(echo "$body" | sed '$d')
  echo "   HTTP $code"
  if [[ "$code" != 2* ]]; then
    echo "$body" | head -c 2000
    echo ""
    return
  fi
  if have_jq && echo "$body" | jq empty 2>/dev/null; then
    echo "$body" | jq .
  else
    echo "$body" | head -c 4000
    echo ""
  fi
}

echo "=== Trading backend audit ==="
echo "BACKEND=$BACKEND"
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

get_json "${BACKEND}/status" "Status"
get_json "${BACKEND}/health/db" "Database"
get_json "${BACKEND}/status/ml" "ML runtime flags (runtime_model_loaded, inference_count)"
get_json "${BACKEND}/status/ml-runtime" "ML per-symbol readiness"
get_json "${BACKEND}/status/model-health?load_model=false" "Model health (artifacts only, fast)"
get_json "${BACKEND}/status/summary" "Status summary (model_loaded, scheduler, etc.)"
get_json "${BACKEND}/exchange/ai-observability" "Exchange AI observability"

if [[ -n "$PUBLIC_HOST" ]]; then
  echo ""
  echo "=== Via nginx (same host, /api prefix) — needs Host: $PUBLIC_HOST ==="
  BASE_API="http://127.0.0.1/api"
  for path in status health/db status/ml status/ml-runtime "status/model-health?load_model=false" status/summary exchange/ai-observability; do
    url="${BASE_API}/${path}"
    label="Nginx /api/${path%%\?*}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "▶ $label"
    echo "   GET $url  (Host: $PUBLIC_HOST)"
    code=$(curl -sS -o /tmp/_audit_body.json -w "%{http_code}" -H "Host: ${PUBLIC_HOST}" "$url") || die "curl failed: $url"
    echo "   HTTP $code"
    if have_jq && [[ -s /tmp/_audit_body.json ]] && jq empty /tmp/_audit_body.json 2>/dev/null; then
      jq . /tmp/_audit_body.json
    else
      head -c 4000 /tmp/_audit_body.json 2>/dev/null || true
      echo ""
    fi
  done
  rm -f /tmp/_audit_body.json
fi

echo ""
echo "=== Done ==="
echo "Tip: install jq for pretty JSON: apt install -y jq"
echo "Tip: PUBLIC_HOST=147.93.96.42 bash $0  — to also hit /api through nginx"
