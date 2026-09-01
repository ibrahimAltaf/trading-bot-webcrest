## API Contract – Core Dashboard & Audit Endpoints

This document captures the **stable backend contracts** that the dashboard and
validation scripts should rely on. All routes below are implemented in the
FastAPI backend under `bot new backend/src/api`.

---

## 1. Exchange – Orders

### `GET /exchange/orders/all`

- **Description**: Order history (NEW/FILLED/CANCELED/EXPIRED) for a symbol.
- **Query params**:
  - `symbol` (string, **required by contract**, e.g. `BTCUSDT`)
  - `limit` (int, optional, default 200, capped at 1000)
- **Behaviour**:
  - If `symbol` is missing or empty:
    - Returns `HTTP 400` with JSON:
      ```json
      {
        "detail": "Query parameter 'symbol' is required, e.g. /exchange/orders/all?symbol=BTCUSDT"
      }
      ```
    - This avoids FastAPI's `422` validation error and gives a clear error to the client.
- **Response (200)**:
  ```json
  {
    "ok": true,
    "symbol": "BTCUSDT",
    "count": 12,
    "orders": [ /* raw Binance Spot API order objects */ ]
  }
  ```

---

## 2. Status & Health

### `GET /status/summary`

- **Description**: Concise runtime health and status information for monitoring.
- **Response (200)**:
  ```json
  {
    "app_version": "1.0",
    "scheduler_state": "running | running(no-job) | stopped | unavailable",
    "last_decision_time": "2024-01-01T12:00:00Z or null",
    "last_successful_market_fetch": "2024-01-01T11:59:00Z or null",
    "last_successful_trade_execution": "2024-01-01T11:58:00Z or null",
    "model_loaded": true,
    "database_connected": true,
    "exchange_connected": true,
    "exchange_detail": "ok | unavailable | <error text>"
  }
  ```

### `GET /status/startup-check`

- **Description**: Aggregated startup/health check for clean boot and audits.
- **Checks covered**:
  - Backend process alive (this endpoint returns HTTP 200).
  - Scheduler initialized (via internal runner state).
  - Database connectivity (`select 1`).
  - Exchange connectivity (light ticker call).
  - Optional dashboard reachability (if `DASHBOARD_URL` env is set).
- **Env**:
  - `DASHBOARD_URL` – optional; if set, backend will attempt a short `GET` (3s timeout).
- **Response (200)**:
  ```json
  {
    "ok": true,
    "env": "dev | prod | ...",
    "app_version": "1.0",
    "scheduler_state": "running | running(no-job) | stopped | unavailable",
    "database_connected": true,
    "exchange_connected": true,
    "dashboard_url": "https://... or null",
    "dashboard_connected": true,
    "dashboard_detail": "HTTP 200 | <error text> | 'DASHBOARD_URL not configured'",
    "last_decision_time": "2024-01-01T12:00:00Z or null",
    "last_successful_market_fetch": "2024-01-01T11:59:00Z or null",
    "last_successful_trade_execution": "2024-01-01T11:58:00Z or null"
  }
  ```

---

## 3. Performance & Decisions

### `GET /exchange/performance`

- **Description**: Detailed live/paper performance metrics.
- **Query params**:
  - `mode`: `"live"` (default) or `"paper"`.
- **Response**: See `src/api/routes_status.py` for full schema.

### `GET /exchange/performance/summary`

- **Description**: Short performance summary for dashboard cards.
- **Query params**:
  - `mode`: `"live"` (default) or `"paper"`.
- **Key fields**:
  - `total_pnl_usdt`
  - `win_rate_pct`
  - `total_trades`
  - `last_signal`
  - `last_signal_reason`
  - `last_signal_ts`

All decision-level transparency (rule vs ML, confidence, override reason, etc.)
is stored in `TradingDecisionLog.signals_json` and exposed via the
`/exchange/auto-trade` pipeline and decision log queries.

### `GET /exchange/performance/ml-vs-rules`

- **Description**: High-level comparison of how often decisions were:
  - `rule_only` (or `rule_only_ml_disabled`)
  - `combined` (rule + ML agree)
  - `ml_override` (ML overrides rule)
- **Metrics returned per bucket**:
  - `total_trades`
  - `wins`
  - `losses`
  - `win_rate_pct`
  - `false_signal_rate_pct`
  - `total_pnl_usdt`
  - `average_return_per_trade_usdt`
  - `average_return_per_trade_pct`
  - `max_drawdown_pct`
  - `sharpe_ratio`
  - `ml_changed_action_count`
- **Response (200)**:
  ```json
  {
    "mode": "live",
    "overall": {
      "total_trades": 40,
      "wins": 22,
      "losses": 18,
      "win_rate_pct": 55.0,
      "false_signal_rate_pct": 45.0,
      "total_pnl_usdt": 120.5,
      "average_return_per_trade_usdt": 3.01,
      "average_return_per_trade_pct": 0.78,
      "max_drawdown_pct": 12.4,
      "sharpe_ratio": 1.18,
      "ml_changed_action_count": 6
    },
    "buckets": {
      "rule_only": { "total_trades": 25, "win_rate_pct": 52.0 },
      "combined": { "total_trades": 10, "win_rate_pct": 60.0 },
      "ml_override": { "total_trades": 5, "win_rate_pct": 80.0 },
      "other": { "total_trades": 0, "win_rate_pct": 0.0 }
    },
    "total": 40
  }
  ```

### `GET /exchange/performance/trades/evaluation`

- **Description**: Trade-by-trade evaluation export for closed positions.
- **Query params**:
  - `mode`: `"live"` (default) | `"paper"`.
- **Each item** includes:
  - `position_id`, `symbol`, `entry_ts`, `exit_ts`, `entry_price`, `entry_qty`,
    `exit_price`, `exit_qty`, `stop_loss`, `take_profit`
  - `entry_reason`, `ml_reason`, `exit_reason`
  - `realized_pnl`, `realized_pnl_pct`
  - Decision audit fields (from closest prior `TradingDecisionLog`):
    - `rule_signal`, `ml_signal`, `ml_confidence`, `combined_signal`,
      `override_reason`, `final_action`
    - `ml_effect`, `ml_changed_final_action`
    - `ml_context` with:
      - `model_name`, `symbol`, `timeframe`, `model_version`
      - `prediction`, `confidence`, `changed_final_action`
      - `model_exists`, `specific_match`
    - `indicators` with:
      - `adx`, `ema_fast`, `ema_slow`, `rsi`, `atr`, `risk_reward`
- **Response (200)**:
  ```json
  {
    "mode": "live",
    "count": 42,
    "items": [
      {
        "position_id": 1,
        "symbol": "BTCUSDT",
        "entry_ts": "2024-01-01T10:00:00Z",
        "exit_ts": "2024-01-01T14:00:00Z",
        "entry_price": 95000.0,
        "entry_qty": 0.01,
        "exit_price": 97000.0,
        "exit_qty": 0.01,
        "pnl": 20.0,
        "pnl_pct": 2.1,
        "rule_signal": "BUY",
        "ml_signal": "BUY",
        "ml_confidence": 0.82,
        "combined_signal": "BUY",
        "override_reason": "Rule + ML agree on BUY",
        "ml_context": {
          "model_name": "BTCUSDT_1h",
          "symbol": "BTCUSDT",
          "timeframe": "1h",
          "model_version": "lstm_v1",
          "prediction": "BUY",
          "confidence": 0.82,
          "changed_final_action": false,
          "model_exists": true,
          "specific_match": true
        }
      }
    ]
  }
  ```

