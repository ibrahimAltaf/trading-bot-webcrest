# AI Trading System — WebCrest

Production-oriented monorepo for an **AI-assisted cryptocurrency trading platform**: a **FastAPI** backend combining rule-based strategy, **LSTM** machine learning, optional **RL** layers, **Binance Spot** integration, **PostgreSQL**, a live **multi-symbol scheduler**, and a **React (Vite)** dashboard for monitoring and audits.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Key improvements](#2-key-improvements)
3. [AI decision flow](#3-ai-decision-flow)
4. [API endpoints](#4-api-endpoints)
5. [Frontend dashboard](#5-frontend-dashboard)
6. [Testing and validation](#6-testing-and-validation)
7. [Runtime validation notes](#7-runtime-validation-notes)
8. [Production readiness](#8-production-readiness)
9. [How to run the project](#9-how-to-run-the-project)
10. [Final summary](#10-final-summary)
11. [Repository layout and docs](#11-repository-layout-and-docs)
12. [Client delivery — Phase 1 handoff](#12-client-delivery--phase-1-handoff)
13. [Phase 2A — Production hardening & shadow mode](#13-phase-2a--production-hardening--shadow-mode-delivered)
14. [Deploying Phase 2A to the VPS](#14-deploying-phase-2a-to-the-vps-copy-paste-commands)

---

## 1. Project overview

**What the system does**

- Ingests market data (Binance REST / klines), computes technical indicators and ML features, and produces **BUY / SELL / HOLD** decisions per configured symbol and timeframe.
- **Fuses** adaptive rule logic with **LSTM** softmax outputs under configurable thresholds; optional portfolio / hybrid risk caps when enabled.
- Persists decisions, positions, orders, and structured **signals** for explainability and compliance-style review.
- Runs an optional **scheduler** that executes trading cycles across **multiple symbols** (e.g. BTC, ETH, SOL) on a fixed interval.

**Technologies**

| Layer    | Stack                                                                                    |
| -------- | ---------------------------------------------------------------------------------------- |
| API      | Python 3, **FastAPI**, Uvicorn, SQLAlchemy, Pydantic                                     |
| ML       | TensorFlow/Keras (`model.keras`), StandardScaler (`scaler.json`), metadata (`meta.json`) |
| Data     | **PostgreSQL**                                                                           |
| Exchange | Binance Spot (testnet or live), signed requests with clock sync                          |
| UI       | **React 19**, **Vite**, TypeScript, TanStack Query, Tailwind                             |

---

## 2. Key improvements

**Strict ML enforcement (`ML_STRICT`)**

- When enabled, the live engine does **not** silently fall back to rules-only trading if ML is required but missing, mis-resolved, or failing in a way that would hide risk.
- Failures surface as explicit outcomes (e.g. `ml_strict_failure`) and structured logs instead of quiet degradation.

**Runtime eligibility (exact model matching)**

- Models resolve to **exact** directories: `ML_MODEL_DIR/<SYMBOL>_<TIMEFRAME>/` (or versioned layout), each containing **`model.keras`**, **`scaler.json`**, **`meta.json`**.
- No permissive pick of a wrong folder; diagnostics report `runtime_eligible`, `exact_match_exists`, and `artifact_exists`.

**Multi-symbol scheduler**

- Configurable list of symbols (default **BTCUSDT**, **ETHUSDT**, **SOLUSDT**) shares one **`TRADE_TIMEFRAME`** from settings; each cycle runs the engine per symbol with its own resolved model path.

**Risk management and position sizing**

- Adaptive strategy and engine apply stops, take-profit, risk-reward, cooldowns, and caps driven by environment and `RiskConfig` (see `src/risk/` and live engine).

**Exception auditing (`engine_exception`)**

- Severe pipeline failures can be recorded with **`final_source: engine_exception`** so dashboards and `/exchange/decisions/recent` expose failures alongside normal decisions.

**Observability (AI metrics, entropy, logs)**

- **`/exchange/performance/ai-observability`** aggregates ML usage rates, runtime posture (including `ml_strict_failure` counts), **Shannon entropy** over `final_source`, and rule/ML/final pattern diversity from recent `TradingDecisionLog` rows.

---

## 3. AI decision flow

**How ML is used**

- Indicators and features feed an LSTM inferencer for the **resolved** model directory; softmax yields SELL/HOLD/BUY-style probabilities and a **confidence** (argmax probability).
- The engine merges **rule_signal** with **ml_signal** using thresholds: agree, override, prioritize, hold-breakout, and moderate influence (see `src/live/auto_trade_engine.py`, `src/live/cycle_decision.py`).

**When ML is valid**

- `runtime_eligible` is true, inference succeeds, and gates pass: decisions may be labeled with sources such as **`combined`**, **`ml_override`**, **`ml_prioritize`**, **`rule_only`**, or **`ml_hold_breakout`** depending on configuration and confidence.

**When ML is missing or fails under `ML_STRICT`**

- Resolution fails (no exact folder / incomplete artifacts) or inference aborts as configured: the cycle can end with **`ml_strict_failure`** — the trading step is aborted for that symbol rather than silently ignoring ML.

**Meaning of key labels**

| Label                 | Meaning                                                                                                                                                                             |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ml_override**       | ML direction and confidence exceed **`ML_OVERRIDE_THRESHOLD`** so ML drives the fused outcome when rules would differ (per engine logic).                                           |
| **ml_prioritize**     | Very high ML confidence (≥ **`ML_PRIORITIZE_THRESHOLD`**) takes precedence in the fusion path.                                                                                      |
| **ml_strict_failure** | Strict ML path required ML but model path invalid, artifacts missing, or ML pipeline failed in a way that triggers abort — **no silent rule-only fill-in** when strict rules apply. |
| **engine_exception**  | Unexpected engine-level failure; audited on the decision/log path for post-mortems.                                                                                                 |

---

## 4. API endpoints

Base URL example: `http://127.0.0.1:8000` (local). All paths are relative to that origin.

**`GET /exchange/performance/ai-observability`**

- Query params: `symbol` (optional filter), `limit` (capped, default 5000).
- Returns JSON with **`ml_usage`** (percent of rows with ML signal/confidence), **`runtime_posture`** (counts by runtime mode, degraded cycles, **`ml_strict_failure_cycles`**), **`decision_diversity`** (distinct rule/ML/final patterns, top patterns, **`final_source_entropy_bits`**), and **`final_source_counts`**.

**`GET /exchange/decisions/recent`**

- Query params: `symbol`, `action`, `limit`.
- Returns recent **`TradingDecisionLog`** rows with transparency fields: **`rule_signal`**, **`ml_signal`**, **`ml_confidence`**, **`combined_signal`**, **`override_reason`**, **`final_action`**, indicators, risk block, **`final_source`**, **`cycle_debug`**, execution flags.

**`GET /exchange/proof`**

- Query param: `symbol` (optional; defaults to configured trade symbol).
- **Unified audit snapshot**: balances, recent decisions, latest decision, PnL/summary slices, orders, positions, recent logs. Subsections are isolated — **`section_errors`** records which subsection failed without invalidating the whole payload.

**`GET /status/model-health/symbols`**

- Query param: `load_model` (optional heavier load per symbol).
- Per-symbol ML resolution: **`model_dir`**, **`exact_match_exists`**, **`runtime_eligible`**, **`reason`**, optional **`runtime_health`** when loading.

Additional useful routes: **`GET /status`**, **`GET /status/ml`**, **`GET /status/summary`**, **`GET /status/model-health`**, **`GET /health/db`**, **`GET /docs`** (OpenAPI).

---

## 5. Frontend dashboard

**Stack:** React 19, Vite, TypeScript, TanStack Query, Tailwind (see `trading-bot-dashboard/`).

**Observability panel**

- Consumes **`/exchange/performance/ai-observability`** (e.g. from `ExchangeMonitor`, `StatusSummary`) to show ML usage, strict-failure counts, and runtime posture.

**Decision table**

- Uses **`/exchange/decisions/recent`** (and related APIs) to show per-row explainability: rules vs ML, confidence, **`final_source`**, and execution.

**Logs view**

- Event and system logs via logs routes and proof-style sections where applicable.

**Symbol switching**

- Dashboard requests pass **`symbol=BTCUSDT`**, **`ETHUSDT`**, **`SOLUSDT`** where supported so operators can isolate behavior per asset.

**Dev proxy:** Vite proxies `/api` to the backend — configure **`VITE_API_BASE_URL`** for production builds pointing at the public API.

---

## 6. Testing and validation

**Automated tests**

- **`pytest`** suite under `bot new backend/src/tests`: **56** collected tests covering API contracts, model selection, symbols, ML fusion paths, cycle decision regression, JSON safety, position sizing, routes helpers, and more.
- Run: `cd "bot new backend"` then `python -m pytest src/tests -q`.

**Contract testing**

- `src/tests/test_api_exchange_contracts.py` validates shapes and behaviors for **`/exchange/decisions/recent`** and **`/exchange/performance/ai-observability`** (including **`final_source`** and **`ml_strict_failure`** handling).

**Multi-cycle and operational validation**

- Scheduler-driven **multi-cycle** runs (e.g. **8+** live intervals) are used in staging or VPS validation to confirm strict ML behavior, logging, and observability under repeated ticks — not all captured in unit tests alone.

**Frontend**

- Production bundle: `cd trading-bot-dashboard && npm install && npm run build` (TypeScript check + Vite build). **`npm run dev`** for local development.

---

## 7. Runtime validation notes

**Binance timestamp (-1021)**

- Signed requests use server time alignment: **`GET /api/v3/time`** offset is applied and **`recvWindow`** is set so clock skew does not trigger **-1021** timestamp errors (see `src/exchange/binance_spot_client.py`).

**ML usage metrics**

- **`ai-observability`** improves visibility into how often ML fields appear in stored signals and how often strict failures occur — useful for tuning thresholds after deployment.

**Live observation of `ml_override` / `ml_prioritize`**

- These labels appear when market conditions and confidence cross configured bars. **Live cycles** (and sufficient decision volume) are needed to see them regularly in **`final_source_counts`** and decision rows.

---

## 8. Production readiness

**From code and tests**

- The architecture supports **strict**, **auditable**, **multi-symbol** operation with comprehensive API tests and contract coverage.

**Operational requirements before relying on production capital**

| Requirement             | Notes                                                                                                                                           |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Correct system time** | VPS/host NTP; avoids Binance signed-request failures.                                                                                           |
| **Valid ML models**     | Per-symbol **`SYMBOL_TIMEFRAME`** folders with all three artifacts; **`TRADE_TIMEFRAME`** must match on-disk layout for every scheduled symbol. |
| **Live validation**     | Smoke **`/status`**, **`/health/db`**, **`/status/model-health`**, and dashboard panels on the target environment.                              |
| **Secrets and DB**      | Strong **`JWT_SECRET`**, valid **`DATABASE_URL`**, non-committed **`.env`**.                                                                    |
| **Process model**       | Single Uvicorn (or systemd) listener per port; avoid duplicate bind races on restart.                                                           |

The system is **ready for production testing** when the above are satisfied; financial risk remains the operator’s responsibility.

---

## 9. How to run the project

### One-click setup (Windows)

For a fully automated setup and launch of both backend and frontend, use the provided **start.cmd** script:

```cmd
start.cmd
```

This script will:

- Set up the backend Python virtual environment (if missing)
- Install backend dependencies
- Install frontend dependencies (if missing)
- Start the backend (Uvicorn/FastAPI) and frontend (Vite/React) servers in separate terminals

> **Note:** Edit your environment variables (e.g. `.env` for backend, `production.env.example` for frontend) as needed before running in production.

---

### Manual steps (advanced)

**Backend**

```bash
cd "bot new backend"
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-ml.txt
cp .env.example .env
# Edit .env: DATABASE_URL, Binance keys, TRADE_*, ML_*, JWT_*, etc.

python -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

**Frontend**

```bash
cd trading-bot-dashboard
npm install
npm run dev
# Production build:
npm run build
```

**Quick health checks**

```bash
curl -s http://127.0.0.1:8000/status
curl -s http://127.0.0.1:8000/health/db
```

---

## 10. Final summary

- The backend behaves as a **strict, AI-aware trading engine**: rules plus LSTM fusion, explicit **`final_source`** labeling, and **no silent ML bypass** when **`ML_STRICT`** is on.
- **Observability** (AI observability endpoint, entropy, decision transparency) and **audit** endpoints (**`/exchange/proof`**) support client and operator review.
- **Multi-symbol** scheduling and per-symbol model resolution make the stack suitable for **BTC / ETH / SOL** (or other configured pairs) from one deployment.
- After automated tests and environment validation, the project is positioned for **production testing** under real keys, real models, and monitored infrastructure.

---

## 11. Repository layout and docs

| Path                      | Role                                                            |
| ------------------------- | --------------------------------------------------------------- |
| `bot new backend/`        | FastAPI app (`src/main.py`), ML, live engine, scheduler, tests  |
| `trading-bot-dashboard/`  | React dashboard                                                 |
| `bot new backend/docs/`   | VPS deployment (`VPS-DEPLOY.md`), API contract |
| `bot new backend/models/` | Trained artifacts per `SYMBOL_TIMEFRAME`                        |

---

## One-click project setup script: `start.cmd`

For convenience, a Windows batch script is provided for one-click setup and launch. Here is what it does:

```batch
@echo off
setlocal

echo ==========================================
echo Setting up backend virtual environment...
echo ==========================================

cd /d "%~dp0bot new backend"

IF NOT EXIST ".venv" (
	echo Creating .venv...
	python -m venv .venv
)

echo Activating .venv and installing backend dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt

echo ==========================================
echo Installing frontend dependencies...
echo ==========================================

cd /d "%~dp0trading-bot-dashboard"

IF NOT EXIST "node_modules" (
	call npm install
)

echo ==========================================
echo Starting backend...
echo ==========================================

start "Backend Server" cmd /k "cd /d ""%~dp0bot new backend"" && call .venv\Scripts\activate.bat && uvicorn src.main:app --reload"

echo ==========================================
echo Starting frontend...
echo ==========================================

start "Frontend Server" cmd /k "cd /d ""%~dp0trading-bot-dashboard"" && npm run dev"

echo Both servers started 🚀
pause
```

This script is located at the root of the repository as `start.cmd`.

**Deploy note:** On Linux servers, prefer a path **without spaces** (e.g. symlink `bot-new-backend`) for systemd and tooling.

**Docker:** `bot new backend/docker-compose.yml` with `.env.production` where applicable.

---

## 12. Client delivery — Phase 1 handoff

### Message you can send to the client

> **Subject: WebCrest AI Trading — Phase 1 delivery update**
>
> Hello,
>
> Phase 1 of the AI trading backend is **deployed and verified** on the production server. Summary:
>
> - **Source code** is on **GitHub** (latest `main` branch):  
>   `https://github.com/ibrahimAltaf/TRADING-BOT-WEBCREST-CLIENT-CON`
> - **ML pipeline** is **operational**: per-symbol models (e.g. BTC/ETH/SOL on the configured timeframe), runtime health endpoints report models loaded and inference running; you can confirm via the audit URLs below.
> - **Swagger (OpenAPI)** is **live** for interactive API testing and audits:  
>   **`http://147.93.96.42/api/docs`**  
>   Use **Try it out** with the **`/api`** server selected so requests hit the API (not the dashboard SPA). **ReDoc:** `http://147.93.96.42/api/redoc` · **OpenAPI JSON:** `http://147.93.96.42/api/openapi.json`
> - **Dashboard** remains at **`http://147.93.96.42/`** (static UI); all REST calls should go through **`/api/...`** on port 80.
> - **Execution lifecycle proof (paper mode)** is enabled for audit: decisions can be forced to execute and will return **`executed=true`** and a generated **`order_id`** like **`paper-<uuid>`**, and paper orders/positions are queryable via API.
> - **Forced execution (audit):** `POST /exchange/auto-trade` accepts **`force_signal` in the query string or in the JSON body** (body wins if both are set). The JSON response includes **`signal`** and **`action`** (same value) so **`force_signal=BUY` → `action=BUY` + `signal=BUY` + paper BUY** when paper mode is on — matching client validation expectations.
>
> **Quick validation URLs** (replace host if you change server/IP):
>
> - API status: `GET http://147.93.96.42/api/status`
> - DB health: `GET http://147.93.96.42/api/health/db`
> - ML flags & inference count: `GET http://147.93.96.42/api/status/ml`
> - Per-symbol ML readiness: `GET http://147.93.96.42/api/status/ml-runtime`
> - Model / artifacts check: `GET http://147.93.96.42/api/status/model-health?load_model=false`
> - AI observability snapshot: `GET http://147.93.96.42/api/exchange/ai-observability`
> - Operational summary: `GET http://147.93.96.42/api/status/summary`
>
> **Execution lifecycle proof (paper mode)**
>
> 1) Force a BUY (returns `executed=true`, **`action`/`signal` = `BUY`**, and `order_id=paper-...`). Use an explicit JSON body (can be empty `{}`) so FastAPI parses `POST` correctly:
>
> ```bash
> curl -sS -X POST "http://147.93.96.42/api/exchange/auto-trade?symbol=BTCUSDT&force_signal=BUY" \
>   -H "Content-Type: application/json" -d '{}' | python3 -m json.tool
> ```
>
> Or pass `force_signal` only in JSON:
>
> ```bash
> curl -sS -X POST "http://147.93.96.42/api/exchange/auto-trade" \
>   -H "Content-Type: application/json" \
>   -d '{"symbol":"BTCUSDT","force_signal":"BUY"}' | python3 -m json.tool
> ```
>
> 2) List paper orders (should include the `paper-...` orderId):
>
> ```bash
> curl -sS "http://147.93.96.42/api/exchange/orders/all?symbol=BTCUSDT&mode=paper" | python3 -m json.tool
> ```
>
> 3) Proof snapshot (paper orders/positions counts should be > 0):
>
> ```bash
> curl -sS "http://147.93.96.42/api/exchange/proof?symbol=BTCUSDT&mode=paper" | python3 -m json.tool
> ```
>
> One-shot server audit (SSH on the VPS, after `git pull`):
>
> ```bash
> PUBLIC_HOST=147.93.96.42 bash "/var/www/TRADING-BOT-WEBCREST-CLIENT-CON/bot new backend/scripts/audit_api_ml.sh"
> ```
>
> **Environment:** Production `.env` on the server must include **`DATABASE_URL`**, Binance keys, and for correct Swagger **Try it out** URLs also **`OPENAPI_SERVER_PREFIX=/api`** and **`FASTAPI_ROOT_PATH=/api`**. For Phase‑1 audit execution proof, keep **`PHASE1_PAPER_EXECUTION=true`**. The app is managed with **systemd** (`tradingbot.service`) and **Gunicorn** on `127.0.0.1:8000`, with **Nginx** proxying **`/api/`** to the backend.
>
> Regards,  
> *WebCrest / Engineering*

### How the deployed stack runs (short)

1. **GitHub:** clone or pull `main` from the repo above.
2. **VPS:** app root is typically `/var/www/trading-backend` (sync from `bot new backend/` via `rsync` or equivalent); **do not** overwrite production `.env` on sync.
3. **Service:** `sudo systemctl restart tradingbot` after code or env changes; check `sudo systemctl status tradingbot` and `journalctl -u tradingbot -n 50` if needed. After restart, wait a few seconds before `curl` to `127.0.0.1:8000` (workers need a short bind window; **`sleep 5`** then **`curl .../status`** avoids a false “connection refused”).
4. **Nginx:** `location /api/` → `http://127.0.0.1:8000/` so public paths are always **`/api/...`**.

Full deployment detail: `docs/VPS-DEPLOYMENT-FULL-GUIDE.md` and `bot new backend/docs/`.

---

## 13. Phase 2A — Production hardening & shadow mode (**delivered**)

All five Phase 2A tracks have landed on `main` (156/156 unit tests passing).
Full spec, promotion gates, and API reference:
**[`docs/PHASE-2A-SPEC.md`](docs/PHASE-2A-SPEC.md)**.
Deploy + rollback + alerting runbook:
**[`docs/PHASE-2A-OPS.md`](docs/PHASE-2A-OPS.md)**.

**Client review (Saad):** start at **[`docs/CLIENT-DELIVERY-INDEX.md`](docs/CLIENT-DELIVERY-INDEX.md)** — all Phase 2A docs, evidence JSON, and 48h test plan in one place.

Track summary:

| # | Track | What it adds |
|---|---|---|
| 1 | Risk engine wiring | Every BUY/SELL (paper/shadow/live) goes through `RiskEngine.validate()`. Rejections persist to `EventLog` and the response carries `blocked=true, reason="risk_rejected:<codes>"`. |
| 2 | Shadow execution | `_execute_*_shadow` uses real balance + filters but simulates the fill. `mode="shadow"` rows in DB so live and shadow are 1:1 comparable. Hard test guard proves no real order is placed. |
| 3 | Restart recovery + idempotency | `Order.client_order_id` column + ALTER-TABLE shim. Startup hydrates `ORDERS / SHADOW_ORDERS / POSITIONS` from DB. Duplicate-window seeded from DB so replays survive restarts. |
| 4 | Exchange-side reconciliation | `GET /safety/exchange-reconcile` compares DB open orders ↔ Binance `openOrders` and DB positions ↔ on-exchange balances (1% tolerance). |
| 5 | Operational hardening | Async webhook + Telegram alerter (`src/safety/alerts.py`) — fires on risk rejections and kill-switch state changes. Configurable via `ALERT_WEBHOOK_URL`, `ALERT_TELEGRAM_*`, `ALERT_MIN_LEVEL`. Deploy + rollback runbook published. |

What is already in the codebase:

- **Execution modes** — tri-state `paper / shadow / live` selector with persistent
  runtime override (`src/execution/mode.py`). Backwards compatible with
  `PHASE1_PAPER_EXECUTION`.
- **Kill switch** — persistent, file-backed, engaged across restarts; checked at
  the entry of every `execute_auto_trade()` (`src/safety/kill_switch.py`).
- **Centralized Risk Engine** — deterministic pre-trade validator with reason
  codes for every gate: trade size, daily loss, exposure %, open positions,
  cooldown, duplicate `client_order_id`, min ML confidence for live
  (`src/safety/risk_engine.py`).
- **Reconciliation skeleton** — read-only drift report between DB and the
  in-memory paper trackers (`src/execution/reconciler.py`).
- **Runtime Binance key rotation from the frontend** — no service restart, no
  SSH session needed. Keys are stored in `app_settings` with secret encrypted at
  rest (when `SECRETS_ENCRYPTION_KEY` is set); `BinanceSpotClient` reads from
  this overlay first, then falls back to `.env` (`src/exchange/runtime_keys.py`,
  `src/api/routes_admin.py`).
- **Live readiness gate** — `GET /safety/live-readiness` returns a single
  `ready_for_live_capital: bool` plus a per-check breakdown (kill switch,
  Binance keys, testnet vs mainnet, execution mode, risk limits, scheduler).
- **Safety + Admin APIs** under the `safety` and `admin` tags in `/docs`:
  - Safety: `GET /safety/status`, `GET /safety/kill-switch`,
    `POST /safety/kill-switch/engage|release`, `GET /safety/limits`,
    `GET /safety/reconcile`, `GET /safety/live-readiness`.
  - Execution mode: `GET /execution/mode`, `POST /execution/mode`,
    `DELETE /execution/mode/override`.
  - Admin (Binance keys): `GET/PUT /admin/binance-keys`,
    `POST /admin/binance-keys/verify`, `DELETE /admin/binance-keys/override`.
    Auth: `X-Admin-Token` header (env `ADMIN_TOKEN`) **or** any
    `Authorization: Bearer <jwt>`.

### 13.1 Saad validation round 2 — trigger provenance, adaptive thresholds, order_origin vs decisions

Every `Order` and `TradingDecisionLog` row now carries `triggered_by`
(`scheduler` | `api_manual` | `proof_forced`) and `cycle_id`, so
`GET /safety/shadow-soak-report` can prove whether a shadow order came from
the unattended APScheduler cycle (`ai_scheduler` — the only category that
counts as genuine autonomous execution) or a manual/script call
(`api_manual_unforced`) or an explicit test call (`proof_forced`).
`FullyAdaptiveStrategy` also gained a posture layer — ML confidence floors,
`atr_vol_threshold`, RSI bands, and SL/TP now recompute every cycle from the
trend/volatility regime instead of staying fixed; the values actually used
each cycle are exposed as `active_thresholds` on every decision
(`FULLY_ADAPTIVE_ENGINE=true` is live).

**Important distinction:** `ai_scheduler_count` counts placed **Orders**;
`/exchange/decisions/recent` counts **every evaluation cycle** (mostly HOLD,
gated before execution) — these are different metrics by design, not a bug.
Full explanation with raw production numbers and the exact client Q&A:
**[`docs/CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md`](docs/CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md)**.

---

## 14. Deploying Phase 2A to the VPS (copy-paste commands)

The VPS deploy directory `/var/www/trading-backend` is **not a git checkout** —
code is shipped via `rsync` from the laptop. Use the steps below exactly.

### 14.1 Engage safety brake (run on VPS first)

Before touching the deploy, lock the system so any in-flight scheduler tick
refuses to execute:

```bash
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/engage" \
  -H "Content-Type: application/json" \
  -d '{"reason":"deploy phase 2a","by":"deploy"}' | python3 -m json.tool | head -5
```

### 14.2 Rsync new code from the laptop

Run **on the laptop** (in a separate terminal):

```bash
cd "/Users/mubeenkhan/Desktop/mercado specs/TRADING-BOT-WEBCREST-CLIENT-CON/bot new backend"

rsync -avz --delete \
  --exclude '.git' \
  --exclude 'venv' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  ./ root@srv759398:/var/www/trading-backend/
```

### 14.3 Restart the service (run on VPS)

```bash
cd /var/www/trading-backend
source venv/bin/activate
pip install -q -r requirements.txt
systemctl restart tradingbot.service
sleep 5
journalctl -u tradingbot.service -n 40 --no-pager | grep -E "STARTUP|migrated|restored|ERROR"
```

Expected lines on first deploy after Phase 2A:

```
[STARTUP] migrated orders.client_order_id column
[STARTUP] runtime trackers restored: {'paper_orders_restored': N, 'shadow_orders_restored': 0, 'paper_positions_restored': M}
```

### 14.4 Smoke checks (run on VPS)

```bash
# 1. Service healthy?
curl -sS http://127.0.0.1:8000/status | python3 -m json.tool | head -10

# 2. New endpoint reachable? (Track 4)
curl -sS "http://127.0.0.1:8000/safety/exchange-reconcile?mode=paper" \
  | python3 -m json.tool | head -20

# 3. Combined safety snapshot.
curl -sS http://127.0.0.1:8000/safety/status \
  | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps({'mode': d['execution_mode']['effective_mode'], 'engaged': d['kill_switch']['engaged'], 'drift': d['reconcile']['drift']}, indent=2))"

# 4. Go/no-go for live capital.
curl -sS http://127.0.0.1:8000/safety/live-readiness | python3 -m json.tool | head -20
```

If `/safety/exchange-reconcile?mode=paper` returns a real JSON body (not
`{"detail":"Not Found"}`), Track 4 is live. If `/safety/status` reports
`drift: []` (or only `severity: info` entries), Track 3 hydration worked.

### 14.5 One-time DB hygiene — clear stale paper positions

Older audit runs left many open paper positions in the DB. With Track 1 wired,
the risk engine's `max_open_positions=3` would block every new paper BUY. Clean
them in a single SQL statement (paper rows only — live / shadow untouched):

```bash
# SQLite (default Phase 1 layout)
sqlite3 /var/www/trading-backend/data/trading.db <<'SQL'
UPDATE positions
SET is_open = 0,
    exit_price = entry_price,
    exit_qty = entry_qty,
    exit_ts  = datetime('now'),
    pnl = 0,
    pnl_pct = 0
WHERE is_open = 1 AND mode = 'paper';
SQL
```

```bash
# PostgreSQL — same statement, run via psql or your DB tool of choice
psql "$DATABASE_URL" -c "
UPDATE positions
SET is_open = false,
    exit_price = entry_price,
    exit_qty   = entry_qty,
    exit_ts    = NOW(),
    pnl = 0,
    pnl_pct = 0
WHERE is_open = true AND mode = 'paper';
"
```

Verify:

```bash
curl -sS http://127.0.0.1:8000/safety/reconcile \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(json.dumps(d['positions'],indent=2))"
```

### 14.6 Release the kill switch + 7-day shadow soak

Once smoke checks are clean and stale paper positions are zeroed out:

```bash
# 1. Flip mode to shadow (real Binance data, simulated fills only).
curl -sS -X POST "http://127.0.0.1:8000/execution/mode" \
  -H "Content-Type: application/json" \
  -d '{"mode":"shadow","reason":"phase 2a shadow soak","by":"ops"}' \
  | python3 -m json.tool | head -5

# 2. Re-enable the scheduler.
curl -sS -X PUT "http://127.0.0.1:8000/settings/scheduler" \
  -H "Content-Type: application/json" -d '{"enabled":true}' | python3 -m json.tool

# 3. Release the kill switch.
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/release" \
  -H "Content-Type: application/json" \
  -d '{"reason":"phase 2a shadow soak start","by":"ops"}' \
  | python3 -m json.tool | head -5
```

The system now runs in shadow mode for ≥ 7 days. Promotion to micro-live is
gated by the checklist in `docs/PHASE-2A-OPS.md` §6.

### 14.7 Rollback (under 2 minutes)

If anything misbehaves after deploy, see the full rollback procedure in
`docs/PHASE-2A-OPS.md` §3 — TL;DR:

```bash
curl -sS -X POST "http://127.0.0.1:8000/safety/kill-switch/engage" \
  -H "Content-Type: application/json" \
  -d '{"reason":"rollback","by":"oncall"}' | python3 -m json.tool | head -3

# … then rsync the previous known-good build back over the deploy dir
# and restart `tradingbot.service`.
```

Kill-switch and execution-mode state files survive restarts, so the brake
stays on until you explicitly release it again.

---

