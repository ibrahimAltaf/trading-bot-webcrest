# Local development — backend and frontend (end-to-end)

Follow these steps to run the project on your machine. The backend folder name contains a space (`bot new backend`) — always quote paths in the terminal.

---

## Prerequisites

| Tool | Recommended version |
|------|---------------------|
| Python | **3.11 or 3.12** (TensorFlow wheels). **Ubuntu 24.04** ships **3.12** only — use `python3` / `python3-venv`, not `python3.11` from apt. |
| Node.js | **18+** (LTS) |
| npm | Bundled with Node |

---

## 1) Backend (`bot new backend`)

### 1.1 Create a virtual environment

```bash
cd "/path/to/TRADING-BOT-WEBCREST-CLIENT-CON/bot new backend"

python3 -m venv .venv        # Ubuntu 24.04: use python3 (3.12). macOS/Homebrew: python3.11 ok too.
source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 1.2 Environment file

Copy the example and fill in your values:

```bash
cp .env.example .env
```

**Local development without PostgreSQL** — you can use SQLite:

```env
DATABASE_URL=sqlite:///./data/local.db
APP_ENV=dev
```

The `data/` directory is created automatically on first run.

**Binance** — for dashboard and exchange routes, set testnet credentials:

```env
BINANCE_TESTNET=true
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
```

You can still open **health, status, and `/docs`** without valid keys; balance and order endpoints may fail.

**ML (Phase 1)** — defaults are fine. On first boot, stub model files can be written if `ML_BOOTSTRAP_STUB=true` and TensorFlow is installed:

```env
ML_ENABLED=true
ML_MODEL_DIR=models
ML_BOOTSTRAP_STUB=true
```

To disable the live trading scheduler locally:

```env
LIVE_SCHEDULER_ENABLED=false
```

(Or turn it off in app settings after the database is seeded.)

### 1.3 Start FastAPI

The project root is the `bot new backend` folder (where the `src/` package lives):

```bash
export PYTHONPATH=.
# optional:
# export DATABASE_URL="sqlite:///$(pwd)/data/local.db"

uvicorn src.main:app --reload --host 127.0.0.1 --port 6000
```

**Quick check (second terminal):**

```bash
curl -s http://127.0.0.1:6000/status | head
curl -s http://127.0.0.1:6000/docs
```

**Useful endpoints:**

- `GET http://127.0.0.1:6000/status`
- `GET http://127.0.0.1:6000/status/ml`
- `GET http://127.0.0.1:6000/status/model-health`
- `GET http://127.0.0.1:6000/exchange/ai-observability`

---

## 2) Frontend (`trading-bot-dashboard`)

### 2.1 Install dependencies and run the dev server

```bash
cd "/path/to/TRADING-BOT-WEBCREST-CLIENT-CON/trading-bot-dashboard"

npm install
npm run dev
```

Default UI: **http://localhost:7000** (or **http://127.0.0.1:7000**). To test from a phone on the same Wi‑Fi, use your PC’s LAN IP and port **7000** (Vite is configured with `host: true`).

### 2.2 API base URL in development

`vite.config.ts` proxies **`/api`** to **`http://127.0.0.1:6000`**.

In dev mode, if `VITE_API_BASE_URL` is empty or points to a local URL, the app uses relative **`/api`** (same origin as the Vite dev server, so you avoid CORS issues).

Optional reference — `trading-bot-dashboard/example.env`:

```env
# Leave empty so the app uses /api and the Vite proxy
VITE_API_BASE_URL=
```

Do not bake a production VPS URL into your local workflow. `trading-bot-dashboard/.env.production` may contain a remote URL — use that only for production builds.

---

## 3) Running both together

| Terminal | Steps |
|----------|--------|
| **A — Backend** | `cd "…/bot new backend"` → `source .venv/bin/activate` → `export PYTHONPATH=.` → `uvicorn src.main:app --reload --host 127.0.0.1 --port 6000` |
| **B — Frontend** | `cd "…/trading-bot-dashboard"` → `npm run dev` |

Open **http://localhost:7000** in the browser. Frontend requests go to **`/api/...`**, which the dev server proxies to the backend on port **6000**.

---

## 4) VPS, Docker, and production (same backend everywhere)

These settings are meant to work on **your laptop**, a **VPS**, and **Docker** without depending on shell `cwd`.

### What is fixed for you

- **`.env` loading** — Reads, from the backend root only: `.env.production` (first, does not override already-set vars), then `.env`, then `.env.local`. Docker `env_file` / systemd `Environment` values stay authoritative.
- **`ML_MODEL_DIR` / `DATA_DIR`** — Resolved relative to the backend project root (folder that contains `src/`), not `cwd`.
- **Start scripts** — Always `cd` to the backend root and set `PYTHONPATH` for you.

### Docker (recommended on VPS)

```bash
cd "/path/to/bot new backend"
cp .env.example .env.production   # then edit with real secrets
docker compose up -d --build
curl -s http://127.0.0.1:6000/status/ml-resolution | head
```

`docker-compose.yml` mounts `./models` and `./data` so ML artifacts survive restarts.

### Bare metal / VPS without Docker

```bash
cd "/path/to/bot new backend"
apt install -y python3 python3-venv python3-pip build-essential   # if needed (Ubuntu)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
chmod +x scripts/run_api.sh scripts/gunicorn_start.sh
# Option A — uvicorn
./scripts/run_api.sh
# Option B — gunicorn + workers
./scripts/gunicorn_start.sh
```

### Hostinger VPS (Ubuntu 24.04) — after manual `uvicorn` works

Typical layout (no space in path): backend at **`/var/www/trading-bot-api`**. Put **`127.0.0.1:6000`** behind nginx (do not expose the API port publicly).

1. **Own the tree** (if the service user is `www-data`):

   ```bash
   sudo chown -R www-data:www-data /var/www/trading-bot-api
   ```

2. **systemd** — create `/etc/systemd/system/trading-api.service`:

   ```ini
   [Unit]
   Description=Trading bot FastAPI
   After=network.target

   [Service]
   Type=simple
   User=www-data
   Group=www-data
   WorkingDirectory=/var/www/trading-bot-api
   Environment=PYTHONPATH=/var/www/trading-bot-api
   Environment=PATH=/var/www/trading-bot-api/.venv/bin:/usr/bin
   Environment=TF_CPP_MIN_LOG_LEVEL=2
   EnvironmentFile=-/var/www/trading-bot-api/.env.production
   ExecStart=/var/www/trading-bot-api/.venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 6000
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   Then:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now trading-api
   sudo systemctl status trading-api
   ```

3. **Nginx** — merge `deploy/nginx-api-location.conf.example` so `location /api/` → `http://127.0.0.1:6000/`, then `sudo nginx -t && sudo systemctl reload nginx`.

4. **Scheduler** — until you want live cycles on the server, set `LIVE_SCHEDULER_ENABLED=false` in `.env.production` (or turn off in app settings).

Template file: `bot new backend/deploy/systemd/trading-api.service.example` (paths there are placeholders; match your server).

**Nginx** — Use `deploy/nginx-api-location.conf.example` so the browser talks to **`https://your-domain/api/...`** and nginx forwards to `127.0.0.1:6000`.

### Frontend build on VPS / CI

Use same-origin API (matches nginx `/api`):

```bash
cd trading-bot-dashboard
cp .env.vps.example .env.production   # sets VITE_API_BASE_URL=/api
npm ci && npm run build
```

Serve `dist/` with nginx; ensure the `/api` location proxies to the backend.

---

## 5) Production-style frontend build (optional, local preview)

```bash
cd "/path/to/TRADING-BOT-WEBCREST-CLIENT-CON/trading-bot-dashboard"
npm run build
npm run preview   # preview the contents of dist/ locally
```

Backend deployment on a server often uses **gunicorn + uvicorn workers** or **uvicorn** alone — see **§4** for scripts.

---

## 6) Why the AI / ML model might not run

The backend only runs the LSTM if **weight files** exist under `models/` (for example `models/BTCUSDT_5m/model.keras` plus `scaler.json` and `meta.json`). Your repo currently has **metadata only** under `models/lstm_v1/...` (JSON) and **no `.keras` / `.h5` / SavedModel folders**, so there is nothing to load until you either:

1. **Install TensorFlow and let the stub generator run** (default `ML_BOOTSTRAP_STUB=true`):  
   `pip install -r requirements.txt` with **Python 3.11 or 3.12**, then restart the API. Stub folders `models/BTCUSDT_5m`, `models/ETHUSDT_5m`, `models/SOLUSDT_5m` are created on startup if missing.

2. **Or train real models** (needs network for Binance data):  
   `PYTHONPATH=. python scripts/train_multi_coin.py --interval 5m`

3. **Check diagnostics:** `GET http://127.0.0.1:6000/status/ml` — fields `runtime_model_loaded`, `runtime_last_error`, and `hint_if_model_missing` explain the current state.

`TRADE_TIMEFRAME` (e.g. `5m`) must match the folder suffix (`BTCUSDT_5m`). Folders like `lstm_v1/BTCUSDT_4h` are **not** used unless you set `ML_MODEL_VERSION=lstm_v1` **and** that folder contains actual weight files (not only JSON).

### Audit / Phase-1 proof endpoints

- **`GET /status/ml-resolution`** — Returns `project_root`, `process_cwd`, resolved `ml_model_dir`, and **per-symbol** paths: `weight_path_in_model_dir`, `check_model_artifacts`, and `resolve_model_selection` (use this to prove where the runtime looks for weights).
- **`GET /exchange/ai-observability`** — `model_loaded`, `inference_count`, `last_prediction`, `ml_confidence`.
- **`GET /status/model-health`** — Includes `healthy` when the model is loaded and `inference_count > 0`.
- **`ML_STARTUP_INFERENCE_SMOKE=true`** (default in `.env.production`) runs **one** real forward pass after load (public klines) so `inference_count` increments even before the scheduler runs (requires outbound HTTPS).
- **`PHASE1_PAPER_EXECUTION=true`** — BUY path records a **paper** order (`orderId` like a UUID in the in-memory `ORDERS` list and DB) so audits can see `executed=true` without a live fill. Set **`false`** when executing real orders on Binance.

**Important:** `ML_MODEL_DIR`, `DATA_DIR`, and `.env` are resolved from the **backend project root** (the folder containing `src/` and `models/`), not from the shell’s current working directory — so systemd/Docker/wrong `cwd` no longer breaks model paths.

---

## 7) Troubleshooting

| Issue | What to try |
|-------|-------------|
| `DATABASE_URL` missing | Set it in `.env` (SQLite example above). |
| TensorFlow fails to install | Use Python **3.11 or 3.12** and run `pip install -r requirements.txt` again. |
| Log: `stub bootstrap failed: No module named 'tensorflow'` | Install full dependencies from `requirements.txt`, or set **`ML_ENABLED=false`** temporarily if you only need API/UI smoke tests. |
| Stub models not created | Ensure TensorFlow is installed and `ML_BOOTSTRAP_STUB=true`; read startup logs. |
| Corporate proxy breaks Binance | For debugging only, try clearing proxies: `HTTP_PROXY=` `HTTPS_PROXY=` |
| Dashboard shows API errors | Confirm the backend is up: `curl http://127.0.0.1:6000/status` |
| CORS | In dev, use the Vite app at port **7000** with the `/api` proxy; don’t point the browser straight at `:6000` for the SPA. |
| Exchange 401 / timeouts | Check Binance keys, testnet flag, firewall, and proxy settings. |

---

## 8) Repository layout

```
TRADING-BOT-WEBCREST-CLIENT-CON/
├── bot new backend/          # FastAPI — scripts/run_api.sh or docker compose
│   ├── deploy/               # systemd + nginx examples
│   └── scripts/              # run_api.sh, gunicorn_start.sh
├── trading-bot-dashboard/    # React + Vite — npm run dev
└── LOCAL_RUN.md              # this file
```

---

*Last updated for local backend + frontend workflow.*
