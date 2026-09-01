# Client Setup Guide — Environment Variables & Local Commands

**Audience:** Saad / external auditors  
**Repo:** https://github.com/ibrahimAltaf/TRADING-BOT-WEBCREST-CLIENT-CON  
**Production (live):** http://147.93.96.42/

---

## Before you start (important)

| Goal | What to use |
|------|-------------|
| Verify **production** shadow soak / order origins | **VPS API only** (see §5) — no local backend required |
| Develop or test code on your laptop | Local setup (§3–§4) |
| See the **7-day soak orders** from the original run | Stored on Neon free-tier soak project; full export blocked by quota. Current VPS uses active Neon instance. See [CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md](./CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md). |

---

## 1. Clone the repository

```bash
git clone https://github.com/ibrahimAltaf/TRADING-BOT-WEBCREST-CLIENT-CON.git
cd TRADING-BOT-WEBCREST-CLIENT-CON
```

---

## 2. Backend — create `.env`

```bash
cd "bot new backend"
cp .env.example .env
```

Edit `.env` with your values. **Never commit `.env` to git.**

### Minimum for local development (SQLite)

```env
APP_ENV=dev
DATABASE_URL=sqlite:///./data/local.db
JWT_SECRET=change-me-local-dev-only
BINANCE_TESTNET=true
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
LIVE_SCHEDULER_ENABLED=false
ML_ENABLED=false
DATA_DIR=./data
```

> **Note:** Local SQLite is empty. It will **not** contain production shadow orders.

### Minimum for local development (PostgreSQL / Neon)

```env
APP_ENV=dev
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST/neondb?sslmode=require
JWT_SECRET=change-me-local-dev-only
BINANCE_TESTNET=true
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
LIVE_SCHEDULER_ENABLED=false
DATA_DIR=./data
```

Ask ops for a **read-only** or **dev** connection string if you need shared data. Do not use production secrets on a personal machine unless approved.

### Production / VPS only (nginx `/api` prefix)

When the API is behind `http://HOST/api/`:

```env
APP_ENV=production
OPENAPI_SERVER_PREFIX=/api
FASTAPI_ROOT_PATH=/api
```

---

## 3. Backend — install & run

```bash
cd "bot new backend"

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

export PYTHONPATH=.

# Create tables (first time only)
python -c "
from src.db.base import Base
from src.db.session import engine
import src.db.models
Base.metadata.create_all(bind=engine)
print('OK: tables created')
"

uvicorn src.main:app --reload --host 127.0.0.1 --port 6000
```

### Verify backend

```bash
curl -s http://127.0.0.1:6000/status
curl -s http://127.0.0.1:6000/health/db
curl -s http://127.0.0.1:6000/docs
```

### Common startup error

```
RuntimeError: DATABASE_URL is missing in .env
```

**Fix:** Ensure `bot new backend/.env` exists and contains a non-empty `DATABASE_URL=` line.

---

## 4. Frontend — install & run (optional)

```bash
cd trading-bot-dashboard
npm install
npm run dev
```

Open: **http://localhost:7000**

Vite proxies `/api` → `http://127.0.0.1:6000` (backend must be running).

### Point frontend at production API (optional)

Create `trading-bot-dashboard/.env.local`:

```env
VITE_API_BASE_URL=http://147.93.96.42/api
```

---

## 5. Production audit APIs (no local setup)

Use these against the **deployed** server:

| Purpose | URL |
|---------|-----|
| Dashboard | http://147.93.96.42/ |
| API docs | http://147.93.96.42/api/docs |
| Health | http://147.93.96.42/api/status |
| DB health | http://147.93.96.42/api/health/db |
| **Shadow soak close-out** | http://147.93.96.42/api/safety/shadow-soak-report?days=7&symbol=BTCUSDT |
| Shadow audit | http://147.93.96.42/api/safety/shadow-audit?symbol=BTCUSDT |
| Shadow orders | http://147.93.96.42/api/exchange/orders/all?mode=shadow&symbol=BTCUSDT&limit=500 |
| Live readiness | http://147.93.96.42/api/safety/live-readiness |

### Download soak report (terminal)

```bash
curl -sS "http://147.93.96.42/api/safety/shadow-soak-report?days=7&symbol=BTCUSDT" \
  | python3 -m json.tool > shadow-soak-closeout.json
```

Review fields:

- `shadow_orders` — each order has `order_origin`
- `shadow_orders_origin_summary` — `proof_forced_count` vs `ai_scheduler_count`

### Forced proof trade (shadow, test only)

```bash
curl -sS -X POST "http://147.93.96.42/api/exchange/auto-trade" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","timeframe":"1h","risk_pct":0.01,"force_signal":"BUY"}'
```

---

## 6. Full environment variable reference

### Required

| Variable | Description | Local example | Production |
|----------|-------------|---------------|------------|
| `DATABASE_URL` | SQLAlchemy DB URL | `sqlite:///./data/local.db` | `postgresql+psycopg2://...` (Neon) |

### App / API

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `dev` | `dev` or `production` |
| `APP_VERSION` | — | Shown in `/status/summary` |
| `DATA_DIR` | `./data` | Runtime data (safety mode files, etc.) |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `FASTAPI_ROOT_PATH` | — | Set `/api` when behind nginx |
| `OPENAPI_SERVER_PREFIX` | — | Swagger base path (`/api`) |
| `CORS_ORIGINS` | — | Extra allowed browser origins (comma-separated) |
| `DASHBOARD_URL` | — | Optional URL for startup-check ping |

### Auth

| Variable | Description |
|----------|-------------|
| `JWT_SECRET` | Login token signing secret (use strong value in production) |
| `JWT_EXPIRE_MINUTES` | Token lifetime (default `10080` = 7 days) |
| `SECRETS_ENCRYPTION_KEY` | Optional AES key for encrypted exchange secrets in DB |

### Binance

| Variable | Description |
|----------|-------------|
| `BINANCE_TESTNET` | `true` = testnet, `false` = mainnet |
| `BINANCE_API_KEY` | Exchange API key |
| `BINANCE_API_SECRET` | Exchange API secret |
| `BINANCE_SPOT_TESTNET_URL` | Default `https://testnet.binance.vision` |
| `BINANCE_SPOT_MAINNET_URL` | Default `https://api.binance.com` |
| `BINANCE_SPOT_FALLBACK_URLS` | Optional comma-separated fallback URLs |

### Machine learning

| Variable | Default | Description |
|----------|---------|-------------|
| `ML_ENABLED` | `true` | Enable ML inference pipeline |
| `ML_STRICT` | `true` | Abort cycle if ML fails (no silent rule-only) |
| `ML_MODEL_DIR` | `models` | Per-symbol model folders |
| `ML_BOOTSTRAP_STUB` | `true` | Write stub weights if models missing |
| `ML_STARTUP_INFERENCE_SMOKE` | `true` | One inference at startup |
| `ML_LOOKBACK` | `50` | Bars for ML features |
| `ML_AGREE_THRESHOLD` | `0.70` | ML agreement threshold |
| `ML_OVERRIDE_THRESHOLD` | `0.60` | ML overrides rules above this confidence |
| `ML_PRIORITIZE_THRESHOLD` | `0.70` | Strong ML path threshold |
| `ML_HOLD_BREAKOUT_ENABLED` | `true` | ML can break HOLD when confident |
| `ML_HOLD_BREAKOUT_MIN_CONFIDENCE` | `0.52` | Min confidence for HOLD breakout |
| `ML_MIN_TRADE_CONFIDENCE` | `0.55` | Min softmax for ML-driven BUY |
| `ML_ABSOLUTE_MIN_CONFIDENCE` | `0.50` | Hard floor for ML confidence |
| `STRICT_ENTRY_GATES` | `false` | Block BUY when any gate fails |

### Trading / strategy

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADE_SYMBOL` | `BTCUSDT` | Default symbol |
| `TRADE_TIMEFRAME` | `5m` | Default candle interval |
| `TRADE_LOOKBACK` | `500` | Klines fetched per cycle |
| `SUPPORTED_TRADING_SYMBOLS` | — | Comma-separated multi-coin list |
| `ADX_THRESHOLD` | `25.0` | Regime: trending vs ranging |
| `ATR_VOL_THRESHOLD` | `2.0` | Volatility gate |
| `EMA_FAST` / `EMA_SLOW` | `20` / `50` | EMA periods |
| `RSI_LEN` | `14` | RSI period |
| `RSI_BUY_MIN` / `RSI_BUY_MAX` | `45` / `70` | RSI buy band (trending) |
| `RSI_TAKE_PROFIT` | `75.0` | RSI take-profit level |
| `BB_LEN` / `BB_STD` | `20` / `2.0` | Bollinger bands |
| `RSI_RANGE_BUY` / `RSI_RANGE_SELL` | `35` / `65` | RSI range rules |
| `MAX_RISK_PER_TRADE` | `0.01` | Risk per trade (fraction) |
| `STOP_LOSS_ATR_MULT` | `2.0` | Stop loss ATR multiplier |
| `TAKE_PROFIT_RR` | `2.0` | Risk/reward target |
| `MAX_OPEN_TRADES` | `1` | Max concurrent positions |
| `COOLDOWN_SECONDS` | `60` | Cooldown after loss |
| `RELAXED_ENTRY_FOR_TESTING` | `false` | Looser entries (testnet only) |

### Execution mode (Phase 2A)

| Variable | Description |
|----------|-------------|
| `EXECUTION_MODE` | `paper` \| `shadow` \| `live` (override file takes precedence) |
| `PHASE1_PAPER_EXECUTION` | Legacy paper flag |
| `SHADOW_USE_FALLBACK_BALANCE` | `true` = use fallback USDT when exchange balance is 0 |
| `SHADOW_USDT_BALANCE` | Fallback sizing balance (default `10000`) |
| `DEMO_OPEN_ONLY` | Demo order flags |
| `DEMO_FILL_MODE` | Demo fill simulation |

### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `LIVE_SCHEDULER_ENABLED` | `false` | Auto-trade scheduler on/off |
| `SCHEDULER_INTERVAL_MINUTES` | `5` | Minutes between cycles |

### Phase 2A risk (optional overrides)

Set in `.env` or use defaults from code:

| Variable | Purpose |
|----------|---------|
| `RISK_MAX_TRADE_NOTIONAL_USDT` | Max notional per trade |
| `RISK_MAX_OPEN_POSITIONS` | Max open positions |
| `RISK_MAX_DAILY_LOSS_USDT` | Daily loss cap |
| `RISK_MAX_DAILY_ORDERS` | Daily order cap |
| `RISK_MAX_EXPOSURE_PCT` | Max exposure % of balance |

### Alerting (optional)

| Variable | Description |
|----------|-------------|
| `ALERT_WEBHOOK_URL` | Generic webhook for alerts |
| `ALERT_TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ALERT_TELEGRAM_CHAT_ID` | Telegram chat ID |
| `ALERT_MIN_LEVEL` | Min level to alert (`WARN`, etc.) |

---

## 7. Order origin values (audit)

| `order_origin` | Meaning |
|----------------|---------|
| `proof_forced` | Manual `POST /exchange/auto-trade` with `force_signal=BUY` or `SELL` |
| `ai_rule` | Scheduler — rule engine |
| `ai_ml` | Scheduler — ML-influenced |
| `ai_combined` | Scheduler — combined pipeline |
| `unknown` | Not linked in decision log |

---

## 8. Related documentation

| Document | Contents |
|----------|----------|
| [CLIENT-DELIVERY-INDEX.md](./CLIENT-DELIVERY-INDEX.md) | Start here — all client docs |
| [CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md](./CLIENT-SAAD-PHASE2A-EXECUTION-FIX-RESPONSE.md) | Phase 2A execution fix + sign-off |
| [LOCAL_RUN.md](../LOCAL_RUN.md) | Full developer local run |
| [PHASE-2A-OPS.md](./PHASE-2A-OPS.md) | Production ops checklist |

---

## 9. Support checklist

If something fails, check in order:

1. `curl http://127.0.0.1:6000/health/db` (local) or `curl http://147.93.96.42/api/health/db` (prod) → must be `"db":"ok"`
2. `.env` has `DATABASE_URL` set
3. Binance keys set if testing exchange routes
4. For production shadow data → use VPS URLs in §5, not local SQLite

**Contact:** Webcrest / Mubeen for ops credentials and production `DATABASE_URL`.
