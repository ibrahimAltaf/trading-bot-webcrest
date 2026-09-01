# VPS deployment (Linux)

This guide assumes Ubuntu 22.04+ (or similar) with **PostgreSQL**, **Nginx**, and **Certbot** for TLS.

**Monorepo:** If you use the single repo **TRADING-BOT-WEBCREST-CLIENT-CON**, clone it once on the VPS. API files live under `bot new backend/`; dashboard under `trading-bot-dashboard/`. You can `sudo mv "bot new backend" /opt/trading-bot-backend` to drop spaces in the API path, or keep the folder name and quote paths in systemd.

## 1. Server prep

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip nginx postgresql postgresql-contrib certbot python3-certbot-nginx git
```

Create a deployment user or use `www-data` as in the systemd unit.

## 2. Code layout (avoid spaces in path)

```bash
sudo mkdir -p /opt/trading-bot-backend
# Upload or clone your repo; copy only `bot new backend` contents into /opt/trading-bot-backend
sudo chown -R $USER:www-data /opt/trading-bot-backend
cd /opt/trading-bot-backend
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Optional ML:
# pip install -r requirements-ml.txt
```

## 3. Environment

```bash
cp .env.example .env
nano .env
```

**Required for production**

- `APP_ENV=production`
- `DATABASE_URL` — PostgreSQL on localhost or managed DB, e.g.  
  `postgresql+psycopg2://USER:PASS@127.0.0.1:5432/tradingbot`
- `BINANCE_API_KEY` / `BINANCE_API_SECRET`
- `BINANCE_TESTNET=false` for mainnet (only when you intend real trading)
- `JWT_SECRET` — long random string (not the example value)

**VPS / dashboard**

- `CORS_ORIGINS=https://app.yourdomain.com` — your dashboard origin(s), comma-separated
- `DASHBOARD_URL=https://app.yourdomain.com` — optional; used by `/status/startup-check`

Initialize DB tables (if not already):

```bash
cd /opt/trading-bot-backend
source venv/bin/activate
python scripts/init_db.py
# or: python -c "from src.db.base import Base; from src.db.session import engine; ..."
```

## 4. Systemd API service

Adjust `User`, paths, and `ExecStart` in `deploy/systemd/trading-bot-api.service`, then:

```bash
sudo cp deploy/systemd/trading-bot-api.service /etc/systemd/system/trading-bot-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot-api
sudo systemctl status trading-bot-api
```

Uvicorn listens on **127.0.0.1:8000** only; Nginx terminates TLS and proxies.

## 5. Nginx + TLS

- Copy `deploy/nginx/api-site.conf`, replace `api.yourdomain.com`, install cert:

```bash
sudo certbot certonly --nginx -d api.yourdomain.com
sudo cp deploy/nginx/api-site.conf /etc/nginx/sites-available/trading-bot-api
sudo ln -sf /etc/nginx/sites-available/trading-bot-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Dashboard (choose one)

**A) Static files on same VPS**

```bash
# On your machine or CI
cd trading-bot-dashboard
cp production.env.example .env.production
# Edit VITE_API_BASE_URL=https://api.yourdomain.com
npm ci && npm run build
rsync -avz dist/ user@vps:/var/www/trading-dashboard/dist/
```

Use `deploy/nginx/dashboard-static.conf` for `app.yourdomain.com` and obtain certs for that host too.

**B) Dashboard on Vercel / Netlify**

- Set `VITE_API_BASE_URL` to `https://api.yourdomain.com` in host env vars.
- On the API server `.env`, set `CORS_ORIGINS` to the exact dashboard origin (e.g. `https://your-app.vercel.app`).

## 7. Smoke checks

- `curl -s https://api.yourdomain.com/status | jq`
- `curl -s https://api.yourdomain.com/status/summary | jq`
- Open `https://api.yourdomain.com/docs` in browser
- Log in on dashboard and hit a read-only exchange endpoint

## 8. Operations

- Logs: `journalctl -u trading-bot-api -f`
- Restart API: `sudo systemctl restart trading-bot-api`
- Scheduler: controlled by `LIVE_SCHEDULER_ENABLED` in DB / env — keep **false** until you trust automation on this host.

## 9. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Do not expose PostgreSQL port 5432 to the public internet.
