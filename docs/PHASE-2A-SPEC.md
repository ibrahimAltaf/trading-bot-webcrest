# Phase 2A — Production Hardening & Shadow Mode

> Status: **all five tracks landed** on `main`. The foundation modules, APIs,
> tests and operational runbook are in place — Phase 2A is ready for an
> internal 7-day shadow soak before micro-live promotion.

Phase 2A turns the validated Phase 1 prototype into a **production-grade
execution platform**. Priorities — in order — are:

1. **Safety** — nothing reaches Binance without passing centralized risk gates.
2. **Synchronization** — local DB ↔ execution engine ↔ exchange always reconciled.
3. **Observability** — every order is fully traceable end-to-end.
4. **Controlled rollout** — paper → shadow → micro live → scaled live.

Profitability optimization is explicitly **out of scope** for Phase 2A.

---

## 1. Architecture additions (already in `main`)

| Module | Purpose |
|---|---|
| `src/execution/mode.py` | Tri-mode selector (`paper` / `shadow` / `live`) with persistent runtime override and backwards compat for `PHASE1_PAPER_EXECUTION`. |
| `src/safety/kill_switch.py` | Persistent hard kill switch — instantly disables trading across restarts; checked at the entry of every `execute_auto_trade()`. |
| `src/safety/risk_engine.py` | Centralized pre-trade `RiskEngine.validate(OrderRequest) → RiskDecision`; deterministic, side-effect-free, env-tunable limits. |
| `src/execution/reconciler.py` | Read-only drift report between DB and the in-memory paper trackers (exchange-side checks land with shadow/live wiring). |
| `src/api/routes_safety.py` | `/safety/*` and `/execution/mode` endpoints (Swagger-documented, tag: `safety`). |
| `src/tests/test_phase2a_safety.py` | ~30 unit + API tests covering the above. |

The kill-switch and risk engine sit **in front of every order**, regardless of
mode. Even paper trades inherit the same guard rails — so the day live mode is
enabled, the safety surface has already been exercised by every prior audit.

---

## 2. Execution modes

```
paper   →  no exchange calls. In-process simulated orders (Phase 1 flow).
shadow  →  real Binance market data + balances. Orders are SIMULATED only.
            Stored under mode="shadow"; never reach the exchange.
live    →  real orders on Binance.
```

Resolution priority (highest first):

1. Runtime override file (`<data_dir>/safety/execution_mode.json`) — set via API.
2. `EXECUTION_MODE=paper|shadow|live`.
3. Legacy `PHASE1_PAPER_EXECUTION=true` → `paper`.
4. Default → `live`.

`POST /execution/mode` is rejected with HTTP 409 if the caller tries to switch
**to live** while the kill switch is engaged.

---

## 3. Kill switch

* Persisted at `<data_dir>/safety/kill_switch.json`.
* `engage(reason)` requires a non-empty reason; idempotent.
* `release(reason)` requires a non-empty reason.
* History is kept (capped at last 50 events).
* `AutoTradeEngine.execute_auto_trade()` short-circuits with
  `executed=false, blocked=true, signal="HOLD"` when engaged — *before* any
  market data or ML call.

### API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/safety/kill-switch` | Current state + history |
| `POST` | `/safety/kill-switch/engage` | Body: `{ "reason": "...", "by": "audit" }` |
| `POST` | `/safety/kill-switch/release` | Body: `{ "reason": "...", "by": "audit" }` |

---

## 4. Risk Engine

`RiskEngine.validate(OrderRequest) → RiskDecision` — every check returns a
machine-readable `reason_code` for dashboards and alerts.

| Check | Reason code | Default behaviour |
|---|---|---|
| Kill switch engaged | `kill_switch_engaged` | Block |
| Invalid side | `invalid_side` | Block |
| Missing symbol | `missing_symbol` | Block |
| Quantity ≤ 0 | `invalid_quantity` | Block |
| Notional < min | `below_min_notional` | Block (5 USDT default) |
| Notional > max | `above_max_trade_notional` | Block (100 USDT default) |
| Exposure % of balance | `exposure_pct_exceeded` | Block (30% default) |
| Max open positions | `max_open_positions` | Block on BUY (3 default) |
| Daily order cap | `max_daily_orders` | Block (50 default) |
| Daily loss cap | `max_daily_loss` | Block (50 USDT default) |
| Cooldown after loss | `cooldown_after_loss` | Block (60s default) |
| Duplicate `client_order_id` | `duplicate_client_order_id` | Block (10s window) |
| Min ML confidence in live | `ml_confidence_below_min_for_live` | Block (0.55 default) |

### Env tuning (all optional)

```
RISK_MAX_TRADE_NOTIONAL_USDT=100
RISK_MAX_OPEN_POSITIONS=3
RISK_MAX_DAILY_LOSS_USDT=50
RISK_MAX_DAILY_ORDERS=50
RISK_MAX_EXPOSURE_PCT=0.30
RISK_MIN_ORDER_NOTIONAL_USDT=5
RISK_COOLDOWN_SECONDS_AFTER_LOSS=60
RISK_DUPLICATE_WINDOW_SECONDS=10
RISK_REQUIRE_KILL_SWITCH_RELEASE=true
RISK_MIN_ML_CONFIDENCE_FOR_LIVE=0.55
```

---

## 5. Reconciliation (Phase 2A scope)

`GET /safety/reconcile` returns a read-only drift report:

* Orders/positions/trades count grouped by `mode` (paper/shadow/live/backtest).
* In-memory paper tracker counts (`src/execution/execution_engine.ORDERS`,
  `src/execution/positions.POSITIONS`).
* Drift findings (e.g. open paper positions in DB but empty in-memory tracker
  after a restart — informational).

Exchange-side reconciliation (Binance `openOrders`, `getAccount`) is wired in
**Phase 2A track 2** alongside shadow / live execution.

---

## 6. Phase 2A delivery tracks

| # | Track | Status |
|---|---|---|
| 1 | **Risk engine integration** — every BUY/SELL (paper/shadow/live) flows through `RiskEngine.validate()`; rejections persist to `EventLog` and the response carries `executed=false, blocked=true, reason="risk_rejected:<codes>"`. SELL bypasses entry-only checks so positions can always close. | ✅ done |
| 2 | **Shadow execution path** — `_execute_buy_shadow` / `_execute_sell_shadow` use real Binance balance + filters but simulate the fill (`shadow-*` orderId, `mode="shadow"` in DB). Hard test guard proves no real order is placed. | ✅ done |
| 3 | **Idempotency + restart recovery** — `Order.client_order_id` column + ALTER-TABLE shim. Every order carries an engine-stable `client_order_id` (paper / shadow / live). On startup `execution.recovery.bootstrap_runtime_state` rehydrates `ORDERS`, `SHADOW_ORDERS`, `POSITIONS` from DB so the reconciler no longer shows false drift after a restart. Duplicate-window check is seeded from the DB so replays survive restarts. | ✅ done |
| 4 | **Exchange-side reconciliation** — `execution.exchange_reconciler.reconcile_with_exchange(db, client)` compares DB-OPEN orders ↔ Binance `openOrders`, and DB positions ↔ on-exchange free balances (1% tolerance). New endpoint `GET /safety/exchange-reconcile?mode=&symbols=`. | ✅ done |
| 5 | **Operational hardening** — async alerter (`src/safety/alerts.py`) with webhook + Telegram sinks; level-filtered via `ALERT_MIN_LEVEL`. Risk rejections and kill-switch engage/release emit structured alerts. Sink errors never propagate. Deploy + rollback runbook in [`docs/PHASE-2A-OPS.md`](./PHASE-2A-OPS.md). | ✅ done |

---

## 7. Promotion gates (Phase 2A → 2B)

Phase 2A is complete and ready to start **micro live trading** when:

1. All Phase 2A modules covered by tests in CI.
2. Risk engine integrated into every execution path; all rejections logged.
3. Shadow mode runs continuously for **≥ 7 days** with no unhandled exceptions.
4. `GET /safety/reconcile` returns `drift == []` under steady state.
5. Kill switch engages/releases verified via dashboard + API.
6. Restart recovery verified (positions + orders survive a process restart).
7. Alerting fires on: failed orders, kill-switch activation, drift detected.
8. Encrypted API key storage in place; live keys never written to git/logs.
9. Deploy + rollback documented and rehearsed once on staging.

---

## 8. Out of scope for Phase 2A

* Multi-asset portfolio risk (Phase 2C+).
* ML retraining pipelines (Phase 2C+).
* RL policy optimization (Phase 3).
* Aggressive position sizing or profitability optimization.

---

## 9. API quick reference

```
GET    /safety/status
GET    /safety/kill-switch
POST   /safety/kill-switch/engage   {"reason": "...", "by": "..."}
POST   /safety/kill-switch/release  {"reason": "...", "by": "..."}
GET    /safety/limits
GET    /safety/reconcile
GET    /safety/live-readiness       — single go/no-go for real-money trading

GET    /execution/mode
POST   /execution/mode              {"mode": "paper|shadow|live", "reason": "..."}
DELETE /execution/mode/override

# Admin: Binance key rotation from the frontend
GET    /admin/binance-keys                 — masked snapshot (never returns secret)
PUT    /admin/binance-keys                 {"api_key": "...", "api_secret": "...", "testnet": false}
POST   /admin/binance-keys/verify          — signed account() call against Binance
DELETE /admin/binance-keys/override        — fall back to .env
```

All endpoints appear under the `safety` or `admin` tag in `/docs`.

### Admin authentication

Either of:

1. `X-Admin-Token: <ADMIN_TOKEN>` header matching the `ADMIN_TOKEN` env var.
2. `Authorization: Bearer <jwt>` from `/auth/login` (any logged-in user).

If neither is provided/valid, admin endpoints return **401**.

---

## 10. Live readiness gate

`GET /safety/live-readiness` is the single endpoint to call before flipping the
system to real-money trading. It returns:

```json
{
  "ok": true,
  "ready_for_live_capital": false,
  "ready_for_live_capital_reason": "one or more required checks not satisfied — see `checks`",
  "blocking_checks": ["binance_keys_present"],
  "warnings": ["secrets_encryption_configured"],
  "checks": [
    {"name": "kill_switch_released",  "ok": true,  "detail": "..."},
    {"name": "binance_keys_present",  "ok": false, "detail": "..."},
    {"name": "secrets_encryption_configured", "ok": false, "severity": "warn", "detail": "..."},
    {"name": "exchange_environment",  "ok": true,  "severity": "info", "detail": "TESTNET ..."},
    {"name": "execution_mode_is_live","ok": false, "severity": "info", "detail": "paper"},
    {"name": "risk_limits_resolved",  "ok": true,  "detail": { ... }},
    {"name": "scheduler_enabled",     "ok": false, "severity": "info", "detail": "..."}
  ],
  "snapshot": { ... }
}
```

`ready_for_live_capital: true` requires **all** of:

* kill switch **released**
* effective execution mode = **live**
* Binance API key + secret **configured** (overlay or env)
* `testnet=false` (mainnet)
* no blocking check failures
