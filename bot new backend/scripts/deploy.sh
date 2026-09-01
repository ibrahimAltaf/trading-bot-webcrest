#!/usr/bin/env bash
# VPS deployment helper (run on server after git pull)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Python =="
python3 --version || true

echo "== Venv (optional) =="
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-ml.txt

echo "== DB migrate (SQLAlchemy creates tables on startup) =="

echo "== Train model (first time) — requires network =="
# PYTHONPATH=. python scripts/train_btc_production.py --interval 5m --limit 8000 --epochs 30

echo "== systemd: copy tradingbot.service and enable =="
echo "Done. Start: uvicorn src.main:app --host 0.0.0.0 --port 8000"
