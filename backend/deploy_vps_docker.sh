#!/usr/bin/env bash
# Deploy trading bot on VPS with Docker + local PostgreSQL (Neon backup restore).
set -euo pipefail

ROOT="${ROOT:-/var/www/TRADING-BOT-WEBCREST}"
BACKEND="${ROOT}/backend"
BK="${ROOT}/backups"
DB_NAME="${POSTGRES_DB:-tradingbot}"
DB_USER="${POSTGRES_USER:-tradingbot}"
DB_PASS="${POSTGRES_PASSWORD:-TradingBot_VPS_2026!}"
NEON_CALM="${NEON_CALM:-postgresql://neondb_owner:npg_QHaW5kByoSt1@ep-calm-lab-adyjzwyk-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

DC=(docker-compose)
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
fi

run_dc() { "${DC[@]}" "$@"; }

mkdir -p "$BK"
cd "$ROOT"

export POSTGRES_DB="$DB_NAME"
export POSTGRES_USER="$DB_USER"
export POSTGRES_PASSWORD="$DB_PASS"

log "Ensure Docker..."
systemctl reset-failed docker 2>/dev/null || true
mkdir -p /etc/docker
[[ -f /etc/docker/daemon.json ]] || echo '{"iptables":false,"ip6tables":false}' > /etc/docker/daemon.json
systemctl start docker
docker info >/dev/null

log "Neon archive backup..."
TS=$(date -u +%Y%m%dT%H%M%SZ)
PRECOPY="${BK}/neon_calm_precopied.dump"
DUMP="${BK}/neon_calm_${TS}.dump"
if [[ -s "$PRECOPY" ]]; then
  DUMP="$PRECOPY"
  log "Using pre-uploaded backup: $(ls -lh "$DUMP" | awk '{print $5}')"
elif docker run --rm --network host postgres:17-alpine pg_dump "$NEON_CALM" -Fc > "$DUMP" 2>"${BK}/pg_dump.err"; then
  log "Backup OK: $(ls -lh "$DUMP" | awk '{print $5}')"
else
  log "WARN: Neon pg_dump failed ($(head -1 "${BK}/pg_dump.err" 2>/dev/null || echo unknown))"
  DUMP=""
fi

log "Write .env.docker from existing backend .env..."
if [[ -f "${BACKEND}/.env" ]]; then
  grep -v '^DATABASE_URL=' "${BACKEND}/.env" > "${ROOT}/.env.docker"
else
  : > "${ROOT}/.env.docker"
fi
{
  echo "APP_ENV=production"
  echo "OPENAPI_SERVER_PREFIX=/api"
  echo "FASTAPI_ROOT_PATH=/api"
  echo "POSTGRES_DB=${DB_NAME}"
  echo "POSTGRES_USER=${DB_USER}"
  echo "POSTGRES_PASSWORD=${DB_PASS}"
} >> "${ROOT}/.env.docker"

log "Stop legacy systemd tradingbot..."
systemctl stop tradingbot 2>/dev/null || true
systemctl disable tradingbot 2>/dev/null || true

log "Start PostgreSQL container first..."
run_dc --env-file "${ROOT}/.env.docker" up -d db
sleep 12

if [[ -n "${DUMP:-}" && -s "$DUMP" ]]; then
  log "Restore Neon backup into Docker PostgreSQL..."
  docker run --rm -i --network container:trading-db postgres:17-alpine \
    pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl --clean --if-exists < "$DUMP" 2>/dev/null || true
else
  log "Skip restore — will init schema after API build"
fi

log "Build API + frontend (may take 10-20 min)..."
docker build --network=host -t trading-bot-webcrest_trading-api ./backend
docker build --network=host -t trading-bot-webcrest_trading-web ./trading-bot-dashboard
run_dc --env-file "${ROOT}/.env.docker" up -d --no-build

if [[ -z "${DUMP:-}" || ! -s "$DUMP" ]]; then
  log "Init empty DB schema..."
  sleep 15
  run_dc exec -T trading-api python scripts/init_db.py 2>/dev/null || \
    run_dc exec -T trading-api python -c "from src.db.session import engine; from src.db.models import Base; Base.metadata.create_all(bind=engine)" || true
fi

log "Update nginx -> docker web :8088..."
NGINX_CONF="/etc/nginx/sites-enabled/trading-bot.conf"
cp "$NGINX_CONF" "${NGINX_CONF}.bak.docker.$(date +%s)" 2>/dev/null || true
cat > "$NGINX_CONF" << 'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 147.93.96.42;

    location /umic-api/ {
        proxy_pass http://127.0.0.1:8010/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
    }

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX
nginx -t && systemctl reload nginx

log "Waiting for API health..."
for i in $(seq 1 36); do
  if curl -sf http://127.0.0.1:6000/status >/dev/null 2>&1; then break; fi
  sleep 10
done

curl -sf http://127.0.0.1:6000/status | head -c 250; echo
curl -sf http://127.0.0.1/api/health/db | head -c 250; echo
run_dc ps
log "DONE — http://147.93.96.42/"
