# TRADING-BOT

A modular **AI-assisted trading and backtesting system** built with **FastAPI**, designed for research, simulation, and live-data integration.
The project supports backtesting, risk configuration, scheduling, exchange integration, and extensible strategy logic.

---

## Tech Stack

- **Python:** 3.11+ (3.11.x recommended; core API installs on 3.13 — see below)
- **API Framework:** FastAPI
- **Server:** Uvicorn
- **Data & Analysis:** pandas, numpy, pyarrow
- **Technical Indicators:** pandas-ta-classic
- **Database:** SQLAlchemy, PostgreSQL (via psycopg2)
- **Scheduling:** APScheduler
- **Exchange API:** python-binance
- **Logging:** loguru
- **Config:** python-dotenv, pydantic-settings

---

## Project Structure (high level)

```
TRADING-BOT/
│
├─ src/
│  ├─ main.py            # FastAPI entry point
│  ├─ api/               # API routes (backtest, logs, paper, etc.)
│  ├─ core/              # config, settings, utilities
│  ├─ db/                # database session / models
│  ├─ scheduler/         # background schedulers
│  └─ strategies/        # trading / backtest logic
│
├─ requirements.txt
├─ .env.example
├─ README.md
└─ ...
```

---

## System Requirements

### Mandatory

- **Python 3.11+ (64-bit)** — **3.11.x** is the best-tested baseline.

  > **TensorFlow (LSTM)** is optional and listed in `requirements-ml.txt`. The main `requirements.txt` avoids pinning TensorFlow so the API, scheduler, and DB stack install cleanly on **Python 3.11–3.13** without a failed pip resolve.

- **Windows / Linux / macOS**
  - Windows tested and supported

### Optional

- PostgreSQL (if DB features are enabled)
- Binance API credentials (for live or paper trading)

---

## Python Version Policy (Important)

This project is validated against:

```
Python 3.11.x
```

Reasons:

- Broadest library support on Windows
- Compatible with modern `pandas`
- Avoids Python 3.12 breaking changes
- Works with `pandas-ta-classic`

---

## Installation

### 1️⃣ Clone the repository

```bash
git clone <your-repo-url>
cd TRADING-BOT
```

---

### 2️⃣ Create and activate virtual environment

#### Windows (recommended)

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
```

#### Linux / macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Verify:

```bash
python --version
```

Expected:

```
Python 3.11.x
```

---

### 3️⃣ Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Optional — ML / LSTM (`tensorflow`, training scripts):

```bash
pip install -r requirements-ml.txt
```

Run tests (after install):

```bash
python -m pytest src/tests -q
```

## Running the Application

### Initialize Database

Before first run, create the database tables:

```bash
python scripts/init_db.py
```

Or:

```bash
python src/db/init_db.py
```

### Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Required settings**:

- `DATABASE_URL` - Your database connection string
- `BINANCE_API_KEY` - Your Binance testnet API key
- `BINANCE_API_SECRET` - Your Binance testnet API secret

**Optional settings**: All adaptive trading strategy parameters (see `.env.example` for defaults)

### Start the FastAPI server

Always run uvicorn via Python (PATH-safe):

```bash
python -m uvicorn src.main:app --reload
```

Expected output:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Production (VPS)

Use **non-reload** uvicorn (or the included systemd unit) and set `CORS_ORIGINS` to your dashboard URL(s). Full steps: **[docs/VPS-DEPLOY.md](docs/VPS-DEPLOY.md)** (Nginx, TLS, PostgreSQL, static dashboard).

---

## Adaptive Trading Strategy (Phase 1)

### Overview

The system includes an **Adaptive Algorithm Trading** engine that autonomously makes BUY/SELL/HOLD decisions based on market conditions with full transparency.

**Key Features**:

- ✅ Two-regime adaptive strategy (Trending vs Ranging markets)
- ✅ Automatic regime detection using ADX
- ✅ Full decision transparency with numeric evidence
- ✅ Risk management (stop-loss, take-profit, position sizing)
- ✅ Dashboard explainability endpoints
- ✅ Works on Binance Spot Testnet (free)

### How It Works

1. **Regime Detection**: System analyzes ADX to determine if market is trending or ranging
2. **Strategy Selection**:
   - **Trending**: EMA crossover + RSI momentum
   - **Ranging**: Bollinger Bands mean-reversion
3. **Decision Generation**: Creates BUY/SELL/HOLD signal with confidence score
4. **Risk Calculation**: Determines entry, stop-loss, and take-profit levels
5. **Execution**: Places order if conditions are met
6. **Logging**: Records decision with full reasoning to database

### API Endpoints

#### Execute Auto-Trade

```bash
POST /exchange/auto-trade
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "timeframe": "5m",
  "risk_pct": 0.01,
  "force_signal": null  // or "BUY"/"SELL" for testing
}
```

#### View Recent Decisions (Dashboard)

```bash
GET /exchange/decisions/recent?symbol=BTCUSDT&limit=50
```

Returns list of recent decisions with:

- Action (BUY/SELL/HOLD)
- Market regime
- All indicator values
- Risk levels
- Human-readable reasoning
- Execution status
- `triggered_by` / `cycle_id` — scheduler vs manual vs proof_forced provenance
- `active_thresholds` / `adaptive_posture` — actual per-cycle gate values and
  confidence floors used (static or regime-adapted, see
  `../docs/CLIENT-SAAD-ORDER-ORIGIN-VS-DECISIONS.md` for the full explanation
  of decision-record counts vs `ai_scheduler_count` on the shadow-soak report)

#### View Latest Decision

```bash
GET /exchange/decisions/latest?symbol=BTCUSDT
```

### Testing the Strategy

1. **Start the server**:

   ```bash
   python -m uvicorn src.main:app --reload
   ```

2. **Generate a decision** (no execution):

   ```bash
   curl -X POST http://localhost:8000/exchange/auto-trade \
     -H "Content-Type: application/json" \
     -d '{"symbol": "BTCUSDT", "timeframe": "5m"}'
   ```

3. **View the decision reasoning**:

   ```bash
   curl http://localhost:8000/exchange/decisions/latest?symbol=BTCUSDT
   ```

4. **Force a BUY for testing**:
   ```bash
   curl -X POST http://localhost:8000/exchange/auto-trade \
     -H "Content-Type: application/json" \
     -d '{"symbol": "BTCUSDT", "timeframe": "5m", "force_signal": "BUY"}'
   ```

### Configuration

All strategy parameters are configurable via `.env`:

```env
# Trading Parameters
TRADE_SYMBOL=BTCUSDT
TRADE_TIMEFRAME=5m
TRADE_LOOKBACK=500

# Regime Detection
ADX_THRESHOLD=25.0

# Trending Rules
EMA_FAST=20
EMA_SLOW=50
RSI_BUY_MIN=45.0
RSI_BUY_MAX=70.0

# Ranging Rules
BB_LEN=20
BB_STD=2.0
RSI_RANGE_BUY=35.0
RSI_RANGE_SELL=65.0

# Risk Management
MAX_RISK_PER_TRADE=0.01
STOP_LOSS_ATR_MULT=2.0
TAKE_PROFIT_RR=2.0
MAX_OPEN_TRADES=1
```

See `.env.example` for complete list and descriptions.

### Documentation

Full strategy specification: [`docs/ADAPTIVE_STRATEGY_SPEC.md`](docs/ADAPTIVE_STRATEGY_SPEC.md)

---

## API Access

- Base URL: `http://127.0.0.1:8000`
- Health / status (example):

  ```
  GET /status
  ```

- Swagger UI:

  ```
  http://127.0.0.1:8000/docs
  ```

---

## Common Commands

| Task                 | Command                                   |
| -------------------- | ----------------------------------------- |
| Activate venv        | `.venv\Scripts\activate`                  |
| Install deps         | `pip install -r requirements.txt`         |
| Run server           | `python -m uvicorn src.main:app --reload` |
| Update deps snapshot | `pip freeze > requirements.lock.txt`      |

---

## Notes & Best Practices

- Do **not** add `src` to `requirements.txt`
- Do **not** upgrade Python without checking pandas / numpy compatibility
- Prefer pinned dependencies for reproducible environments
- On Windows, always use `python -m uvicorn` instead of `uvicorn`

---

## Troubleshooting

### `uvicorn` not recognized

Use:

```bash
python -m uvicorn src.main:app --reload
```

### Dependency conflicts

- Confirm Python version is **3.11**
- Recreate venv if needed:

```bash
rmdir /s /q .venv
py -3.11 -m venv .venv
```
#   T r a d i n g - B o t - F r o n t e n d - W e b c r e s t  
 